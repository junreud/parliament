package dev.parliament.beta;

import com.fasterxml.jackson.annotation.JsonInclude;
import dev.parliament.tracking.TrackingAdminAuthorization;
import java.time.Clock;
import java.time.Instant;
import java.util.Map;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseCookie;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ServerWebExchange;
import org.springframework.web.server.ResponseStatusException;
import reactor.core.publisher.Mono;

@RestController
@ConditionalOnProperty(prefix = "beta", name = "enabled", havingValue = "true")
public class BetaController {
    private static final String COOKIE = "parliament_beta";
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record Participation(boolean participating, String csrfToken) {}
    private final BetaRepository repository;
    private final BetaPolicy policy;
    private final BetaRateLimiter limiter;
    private final Clock clock;
    private final TrackingAdminAuthorization admin;

    public BetaController(BetaRepository repository, BetaPolicy policy, BetaRateLimiter limiter,
            @Qualifier("betaClock") Clock clock, @Value("${beta.admin-key:}") String adminKey) {
        this.repository = repository;
        this.policy = policy;
        this.limiter = limiter;
        this.clock = clock;
        this.admin = new TrackingAdminAuthorization(adminKey);
    }

    @GetMapping("/api/v1/beta/session")
    public Mono<Participation> session(ServerWebExchange exchange) {
        prepare(exchange, "session", 120, 60);
        return repository.current(token(exchange), clock.instant())
                .map(s -> new Participation(true, s.csrfToken()))
                .defaultIfEmpty(new Participation(false, null));
    }

    @PostMapping("/api/v1/beta/participants")
    @ResponseStatus(HttpStatus.CREATED)
    public Mono<Participation> enroll(@RequestBody Map<String, Object> input, ServerWebExchange exchange) {
        exchange.getResponse().getHeaders().setCacheControl("no-store");
        policy.authorizeOrigin(exchange.getRequest().getHeaders().getOrigin());
        BetaPolicy.Enrollment enrollment = policy.enrollment(input);
        // Behind the same-origin proxy many people share a socket peer. Normalize before limiting;
        // the per-email hash exists only in this process for one hour, never in persistent storage.
        limiter.check(policy.hash(enrollment.email()), "enrollment-email", 5, 3600, clock.instant());
        prepare(exchange, "enrollment", 200, 3600);
        Mono<Participation> create = Mono.defer(() -> repository.enroll(enrollment, clock.instant()).map(result -> {
            exchange.getResponse().addCookie(cookie(result.token(), BetaPolicy.RETENTION));
            return new Participation(true, result.csrfToken());
        }));
        if (!policy.validToken(token(exchange))) return create;
        return repository.current(token(exchange), clock.instant())
                .map(session -> new Participation(true, session.csrfToken())).switchIfEmpty(create);
    }

    @PostMapping("/api/v1/beta/events")
    @ResponseStatus(HttpStatus.ACCEPTED)
    public Mono<Void> event(@RequestBody Map<String, Object> input, ServerWebExchange exchange) {
        prepare(exchange, "events", 120, 60);
        return authorized(exchange).flatMap(session -> {
            BetaPolicy.Event event = policy.event(input);
            limiter.check(session.participantId(), "participant-events", 60, 60, clock.instant());
            return repository.record(session, event, clock.instant());
        });
    }

    @PostMapping("/api/v1/beta/acquisition")
    @ResponseStatus(HttpStatus.ACCEPTED)
    public Mono<Void> acquisition(@RequestBody Map<String, Object> input, ServerWebExchange exchange) {
        prepare(exchange, "acquisition", 30, 60);
        policy.authorizeOrigin(exchange.getRequest().getHeaders().getOrigin());
        return repository.acquisition(policy.acquisition(input), clock.instant());
    }

    @PostMapping("/api/v1/beta/withdraw")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public Mono<Void> withdraw(ServerWebExchange exchange) {
        prepare(exchange, "withdraw", 10, 60);
        return authorized(exchange).flatMap(s -> repository.withdraw(s.participantId()))
                .doOnSuccess(ignored -> exchange.getResponse().addCookie(cookie("", java.time.Duration.ZERO)));
    }

    @GetMapping("/admin/beta/report")
    public Mono<BetaReport.Report> report(
            @RequestHeader(name = "X-Parliament-Ingestion-Key", required = false) String key,
            @RequestParam Instant from, @RequestParam Instant to, ServerWebExchange exchange) {
        admin.authorize(key);
        prepare(exchange, "report", 30, 60);
        return repository.report(from, to, clock.instant());
    }

    @ExceptionHandler({IllegalArgumentException.class, org.springframework.web.server.ServerWebInputException.class})
    @ResponseStatus(HttpStatus.BAD_REQUEST)
    public Map<String, String> invalid() { return Map.of("error", "invalid beta request"); }

    private Mono<BetaRepository.Session> authorized(ServerWebExchange exchange) {
        return repository.current(token(exchange), clock.instant())
                .switchIfEmpty(Mono.error(new ResponseStatusException(HttpStatus.UNAUTHORIZED, "beta participation required")))
                .doOnNext(session -> policy.authorizeMutation(exchange.getRequest().getHeaders().getOrigin(),
                        exchange.getRequest().getHeaders().getFirst("X-CSRF-Token"), session.csrfToken()));
    }

    private void prepare(ServerWebExchange exchange, String action, int maximum, long seconds) {
        exchange.getResponse().getHeaders().setCacheControl("no-store");
        String peer = exchange.getRequest().getRemoteAddress() == null ? "unknown"
                : exchange.getRequest().getRemoteAddress().getAddress().getHostAddress();
        // Forwarded headers are deliberately not trusted for rate-limit identity.
        limiter.check(peer, action, maximum, seconds, clock.instant());
        limiter.check("global", "all-" + action, maximum * 20, seconds, clock.instant());
    }
    private String token(ServerWebExchange exchange) {
        var value = exchange.getRequest().getCookies().getFirst(COOKIE);
        return value == null ? null : value.getValue();
    }
    private ResponseCookie cookie(String token, java.time.Duration age) {
        return ResponseCookie.from(COOKIE, token).httpOnly(true).secure(policy.secure())
                .sameSite("Strict").path("/api/v1/beta").maxAge(age).build();
    }
}
