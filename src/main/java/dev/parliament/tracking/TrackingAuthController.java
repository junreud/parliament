package dev.parliament.tracking;

import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseCookie;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ServerWebExchange;

import reactor.core.publisher.Mono;

import java.time.Duration;
import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/api/v1")
@ConditionalOnProperty(prefix = "tracking", name = "enabled", havingValue = "true")
public class TrackingAuthController {
    public record EmailRequest(String email) {}

    public record TokenRequest(String token) {}

    public record FollowsRequest(List<TrackingAuthRepository.Follow> follows, String frequency) {}

    private final TrackingAuthRepository repository;
    private final TrackingAuthPolicy policy;

    public TrackingAuthController(TrackingAuthRepository repository, TrackingAuthPolicy policy) {
        this.repository = repository;
        this.policy = policy;
    }

    @PostMapping("/auth/request-link")
    @ResponseStatus(HttpStatus.ACCEPTED)
    public Mono<Map<String, Boolean>> requestLink(
            @RequestBody EmailRequest request, ServerWebExchange exchange) {
        noStore(exchange);
        policy.authorizeOrigin(exchange.getRequest().getHeaders().getOrigin());
        String client =
                exchange.getRequest().getRemoteAddress() == null
                        ? "unknown"
                        : exchange.getRequest().getRemoteAddress().getAddress().getHostAddress();
        return repository.requestLink(request.email(), client).thenReturn(Map.of("accepted", true));
    }

    @PostMapping("/auth/verify")
    public Mono<Map<String, Boolean>> verify(
            @RequestBody TokenRequest request, ServerWebExchange exchange) {
        noStore(exchange);
        policy.authorizeOrigin(exchange.getRequest().getHeaders().getOrigin());
        return repository
                .verify(request.token())
                .map(
                        session -> {
                            cookie(exchange, session.token(), Duration.ofDays(30));
                            return Map.of("authenticated", true);
                        });
    }

    @GetMapping("/me")
    public Mono<TrackingAuthRepository.Me> me(ServerWebExchange exchange) {
        noStore(exchange);
        return repository.me(sessionToken(exchange));
    }

    @PutMapping("/me/follows")
    public Mono<TrackingAuthRepository.Me> follows(
            @RequestBody FollowsRequest request, ServerWebExchange exchange) {
        noStore(exchange);
        return authorized(exchange)
                .flatMap(
                        session ->
                                repository
                                        .replaceFollows(
                                                session.userId(),
                                                request.follows(),
                                                request.frequency())
                                        .then(repository.me(session.token())));
    }

    @PostMapping("/auth/logout")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public Mono<Void> logout(ServerWebExchange exchange) {
        noStore(exchange);
        return authorized(exchange)
                .flatMap(
                        session ->
                                repository
                                        .logout(session.token())
                                        .doOnSuccess(
                                                ignored -> cookie(exchange, "", Duration.ZERO)));
    }

    @PostMapping("/auth/unsubscribe")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public Mono<Void> unsubscribe(@RequestBody TokenRequest request, ServerWebExchange exchange) {
        noStore(exchange);
        return repository.unsubscribe(request.token());
    }

    private Mono<TrackingAuthRepository.Session> authorized(ServerWebExchange exchange) {
        return repository
                .current(sessionToken(exchange))
                .switchIfEmpty(Mono.error(TrackingAuthRepository.unauthorized()))
                .map(
                        session -> {
                            policy.authorizeMutation(
                                    exchange.getRequest().getHeaders().getOrigin(),
                                    exchange.getRequest().getHeaders().getFirst("X-CSRF-Token"),
                                    session.csrfToken());
                            return session;
                        });
    }

    private static String sessionToken(ServerWebExchange exchange) {
        var cookie = exchange.getRequest().getCookies().getFirst("parliament_session");
        return cookie == null ? null : cookie.getValue();
    }

    private void cookie(ServerWebExchange exchange, String value, Duration age) {
        exchange.getResponse()
                .addCookie(
                        ResponseCookie.from("parliament_session", value)
                                .httpOnly(true)
                                .secure(policy.secure())
                                .sameSite("Lax")
                                .path("/")
                                .maxAge(age)
                                .build());
    }

    private static void noStore(ServerWebExchange exchange) {
        exchange.getResponse().getHeaders().setCacheControl("no-store");
    }

    @ExceptionHandler(IllegalArgumentException.class)
    @ResponseStatus(HttpStatus.BAD_REQUEST)
    public Map<String, String> invalid(IllegalArgumentException error) {
        return Map.of("error", error.getMessage() == null ? "invalid request" : error.getMessage());
    }
}
