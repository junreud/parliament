package dev.parliament.knowledge;

import java.util.Map;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;
import reactor.core.publisher.Mono;

/** Public GET only. No candidate, review or publication write path is exposed. */
@RestController
@ConditionalOnProperty(prefix = "knowledge", name = "enabled", havingValue = "true")
public final class IssueReadingController {
    private final IssueReadingReads reads;
    public IssueReadingController(IssueReadingReads reads) { this.reads = reads; }

    @GetMapping("/api/v1/issues/{id}/reading")
    public Mono<ResponseEntity<IssueReadingReads.Reading>> read(@PathVariable String id) {
        return reads.read(id).map(value -> ResponseEntity.ok().header(HttpHeaders.CACHE_CONTROL, "no-store").body(value));
    }

    @ExceptionHandler(ResponseStatusException.class)
    public ResponseEntity<Map<String, String>> unavailable(ResponseStatusException error) {
        String code = switch (error.getStatusCode().value()) {
            case 400 -> "invalid_issue_id";
            case 404 -> "reading_not_found";
            case 409 -> "reading_version_conflict";
            default -> "reading_unavailable";
        };
        var status = switch (error.getStatusCode().value()) {
            case 400 -> HttpStatus.BAD_REQUEST;
            case 404 -> HttpStatus.NOT_FOUND;
            case 409 -> HttpStatus.CONFLICT;
            default -> HttpStatus.SERVICE_UNAVAILABLE;
        };
        return ResponseEntity.status(status).header(HttpHeaders.CACHE_CONTROL, "no-store").body(Map.of("error", code));
    }
}
