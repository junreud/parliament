package dev.parliament.tracking;

import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.*;

import reactor.core.publisher.Mono;

import java.util.Map;

@RestController
@RequestMapping("/admin/tracking/digests")
@ConditionalOnProperty(prefix = "tracking", name = "enabled", havingValue = "true")
public class TrackingDigestController {
    private final TrackingDigests digests;
    private final TrackingAdminAuthorization auth;

    public TrackingDigestController(TrackingDigests digests, TrackingAdminAuthorization auth) {
        this.digests = digests;
        this.auth = auth;
    }

    @PostMapping("/build")
    public Mono<TrackingDigests.Result> build(
            @RequestHeader(name = "X-Parliament-Ingestion-Key", required = false) String key,
            @RequestBody TrackingDigests.BuildRequest request) {
        auth.authorize(key);
        return digests.build(request.frequency(), request.from(), request.to());
    }

    @ExceptionHandler(IllegalArgumentException.class)
    @ResponseStatus(HttpStatus.BAD_REQUEST)
    public Map<String, String> invalid(IllegalArgumentException error) {
        return Map.of("error", error.getMessage() == null ? "invalid request" : error.getMessage());
    }
}
