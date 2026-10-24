package dev.parliament.tracking;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;

import org.springframework.core.io.ClassPathResource;

import java.io.IOException;
import java.util.List;

/** Curated definitions, deliberately containing no invented activity. */
public final class TrackingIssues {
    public record Issue(String id, String title, String topic, String description) {}

    private final List<Issue> issues;

    public TrackingIssues() {
        try (var stream = new ClassPathResource("tracking/issues.json").getInputStream()) {
            issues = new ObjectMapper().readValue(stream, new TypeReference<List<Issue>>() {});
        } catch (IOException ex) {
            throw new IllegalStateException("issue definitions unavailable", ex);
        }
    }

    public List<Issue> all() {
        return issues;
    }

    public Issue find(String id) {
        return issues.stream()
                .filter(issue -> issue.id().equals(id))
                .findFirst()
                .orElseThrow(TrackingRepository::notFound);
    }
}
