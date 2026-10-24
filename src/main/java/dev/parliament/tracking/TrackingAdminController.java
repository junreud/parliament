package dev.parliament.tracking;

import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.*;

import reactor.core.publisher.Mono;

import java.util.Map;

@RestController
@RequestMapping("/admin/tracking")
@ConditionalOnProperty(prefix = "tracking", name = "enabled", havingValue = "true")
public class TrackingAdminController {
    public record Review(boolean approved, String reviewer, String correctionReason) {}

    private final TrackingRepository repository;
    private final TrackingProjection projection;
    private final TrackingAdminAuthorization auth;

    public TrackingAdminController(
            TrackingRepository repository,
            TrackingProjection projection,
            TrackingAdminAuthorization auth) {
        this.repository = repository;
        this.projection = projection;
        this.auth = auth;
    }

    @PostMapping("/events")
    public Mono<TrackingRepository.ImportResult> importEvent(
            @RequestHeader(name = "X-Parliament-Ingestion-Key", required = false) String key,
            @RequestBody Activity activity) {
        auth.authorize(key);
        return repository.importDraft(activity);
    }

    @GetMapping("/review")
    public Mono<TrackingController.Items<Activity>> reviewQueue(
            @RequestHeader(name = "X-Parliament-Ingestion-Key", required = false) String key) {
        auth.authorize(key);
        return repository.drafts().collectList().map(TrackingController.Items::new);
    }

    @PostMapping("/events/{id}/versions/{version}/review")
    public Mono<?> review(
            @RequestHeader(name = "X-Parliament-Ingestion-Key", required = false) String key,
            @PathVariable String id,
            @PathVariable String version,
            @RequestBody Review request) {
        auth.authorize(key);
        if (request.approved())
            return repository.publish(id, version, request.reviewer(), request.correctionReason());
        return repository.reject(id, version).thenReturn(Map.of("state", "rejected"));
    }

    @PostMapping("/project")
    public Mono<TrackingProjection.Result> project(
            @RequestHeader(name = "X-Parliament-Ingestion-Key", required = false) String key,
            @RequestBody TrackingProjection.Contract request) {
        auth.authorize(key);
        return projection.project(request);
    }

    @ExceptionHandler(IllegalArgumentException.class)
    @ResponseStatus(HttpStatus.BAD_REQUEST)
    public Map<String, String> invalid(IllegalArgumentException error) {
        return Map.of("error", error.getMessage() == null ? "invalid request" : error.getMessage());
    }
}
