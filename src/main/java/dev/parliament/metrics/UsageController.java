package dev.parliament.metrics;

import dev.parliament.tracking.TrackingAdminAuthorization;
import dev.parliament.tracking.TrackingAuthPolicy;
import dev.parliament.tracking.TrackingAuthRepository;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ServerWebExchange;
import reactor.core.publisher.Mono;
import java.time.Instant;
import java.util.Map;

@RestController
@ConditionalOnProperty(prefix="tracking", name="enabled", havingValue="true")
public class UsageController {
    public record Input(String event, Boolean rating) {}
    private final UsageRepository usage;
    private final TrackingAuthRepository auth;
    private final TrackingAuthPolicy policy;
    private final TrackingAdminAuthorization admin;
    public UsageController(UsageRepository usage, TrackingAuthRepository auth,
                           TrackingAuthPolicy policy, TrackingAdminAuthorization admin) {
        this.usage=usage; this.auth=auth; this.policy=policy; this.admin=admin;
    }
    @PostMapping("/api/v1/usage")
    @ResponseStatus(HttpStatus.ACCEPTED)
    public Mono<Void> record(@RequestBody Input input, ServerWebExchange exchange) {
        exchange.getResponse().getHeaders().setCacheControl("no-store");
        var cookie=exchange.getRequest().getCookies().getFirst("parliament_session");
        return auth.current(cookie==null ? null : cookie.getValue())
                .switchIfEmpty(Mono.error(new org.springframework.web.server.ResponseStatusException(HttpStatus.UNAUTHORIZED,"authentication required")))
                .flatMap(session -> {
                    policy.authorizeMutation(exchange.getRequest().getHeaders().getOrigin(),
                            exchange.getRequest().getHeaders().getFirst("X-CSRF-Token"),session.csrfToken());
                    return usage.record(session.userId(), input.event(), input.rating(), Instant.now());
                });
    }
    @GetMapping("/admin/tracking/metrics")
    public Mono<UsageRepository.Report> report(
            @RequestHeader(name="X-Parliament-Ingestion-Key",required=false) String key,
            @RequestParam Instant from, @RequestParam Instant to, ServerWebExchange exchange) {
        admin.authorize(key);
        exchange.getResponse().getHeaders().setCacheControl("no-store");
        return usage.report(from,to,Instant.now());
    }
    @ExceptionHandler(IllegalArgumentException.class)
    @ResponseStatus(HttpStatus.BAD_REQUEST)
    public Map<String,String> invalid() { return Map.of("error","invalid usage request"); }
}
