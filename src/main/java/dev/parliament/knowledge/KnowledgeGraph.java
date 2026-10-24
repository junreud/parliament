package dev.parliament.knowledge;

import java.time.Instant;
import java.time.LocalDate;
import java.util.List;

/** Public graph contains bounded, evidence-backed connections, never storage paths. */
public record KnowledgeGraph(String rootKey, List<Node> nodes, List<Edge> edges,
        boolean truncated, String visibility) {
    public record Node(String key, String id, String kind, String label, String href, String version) {}
    public record Edge(String id, String sourceKey, String targetKey, String type, String label,
            List<String> evidenceIds, String batchId, Instant reviewedAt,
            LocalDate validFrom, LocalDate validUntil, Instant observedAt) {}
    public record Person(String id, String name, String kind, String position,
            String organizationId, String organizationName, Instant observedAt) {}
    public record People(List<Person> items, String nextCursor) {}
}
