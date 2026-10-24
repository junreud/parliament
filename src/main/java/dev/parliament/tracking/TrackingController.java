package dev.parliament.tracking;

import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.*;

import reactor.core.publisher.Mono;

import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/api/v1")
@ConditionalOnProperty(prefix = "tracking", name = "enabled", havingValue = "true")
public class TrackingController {
    public record Items<T>(List<T> items) {}

    private final TrackingRepository repository;
    private final TrackingDirectory directory;
    private final TrackingIssues issues;

    public TrackingController(
            TrackingRepository repository, TrackingDirectory directory, TrackingIssues issues) {
        this.repository = repository;
        this.directory = directory;
        this.issues = issues;
    }

    @GetMapping("/activities")
    public Mono<TrackingRepository.Page> activities(
            @RequestParam(required = false) String personId,
            @RequestParam(required = false) String topic,
            @RequestParam(required = false) String billId,
            @RequestParam(required = false) String type,
            @RequestParam(required = false) String cursor,
            @RequestParam(defaultValue = "20") int limit) {
        if (limit < 1 || limit > 100) throw new IllegalArgumentException("limit must be 1..100");
        return repository.feed(
                personId,
                topic,
                billId,
                type,
                null,
                cursor == null ? null : TrackingCursor.decode(cursor),
                limit);
    }

    @GetMapping("/activities/{id}")
    public Mono<Activity> activity(
            @PathVariable String id, @RequestParam(required = false) String version) {
        return repository.detail(id, version);
    }

    @GetMapping("/activities/{id}/history")
    public Mono<Items<TrackingRepository.History>> history(@PathVariable String id) {
        return repository
                .history(id)
                .collectList()
                .flatMap(
                        items ->
                                items.isEmpty()
                                        ? Mono.error(TrackingRepository.notFound())
                                        : Mono.just(new Items<>(items)));
    }

    @GetMapping("/search")
    public Mono<TrackingRepository.Page> search(
            @RequestParam String q,
            @RequestParam(required = false) String cursor,
            @RequestParam(defaultValue = "20") int limit) {
        return repository.feed(
                null,
                null,
                null,
                null,
                q,
                cursor == null ? null : TrackingCursor.decode(cursor),
                limit);
    }

    @GetMapping("/people")
    public Mono<Items<TrackingDirectory.Person>> people(
            @RequestParam(required = false) String query) {
        return directory.people(query).collectList().map(Items::new);
    }

    @GetMapping("/people/{id}")
    public Mono<TrackingDirectory.Person> person(@PathVariable String id) {
        return directory.person(id);
    }

    @GetMapping("/bills")
    public Mono<Items<TrackingDirectory.Bill>> bills(@RequestParam(required = false) String query) {
        return directory.bills(query).collectList().map(Items::new);
    }

    @GetMapping("/bills/{id}")
    public Mono<TrackingDirectory.Bill> bill(@PathVariable String id) {
        return directory.bill(id);
    }

    @GetMapping("/issues")
    public Items<TrackingIssues.Issue> issues() {
        return new Items<>(issues.all());
    }

    @GetMapping("/issues/{id}")
    public Mono<Map<String, Object>> issue(@PathVariable String id) {
        var issue = issues.find(id);
        return repository
                .feed(null, id, null, null, null, null, 100)
                .map(
                        page ->
                                Map.of(
                                        "id",
                                        issue.id(),
                                        "title",
                                        issue.title(),
                                        "topic",
                                        issue.topic(),
                                        "description",
                                        issue.description(),
                                        "activities",
                                        page.items()));
    }

    @GetMapping("/coverage")
    public Mono<Items<TrackingDirectory.Coverage>> coverage() {
        return directory.coverage().collectList().map(Items::new);
    }

    @ExceptionHandler(IllegalArgumentException.class)
    @ResponseStatus(HttpStatus.BAD_REQUEST)
    public Map<String, String> invalid(IllegalArgumentException error) {
        return Map.of("error", error.getMessage() == null ? "invalid request" : error.getMessage());
    }
}
