package dev.parliament.knowledge;

import dev.parliament.tracking.Activity;
import java.time.Instant;
import java.time.LocalDate;
import java.util.List;

/** Immutable input snapshot. Publication and source identity are separate decisions. */
public record KnowledgeBatch(String id, String issueId, List<Entity> entities,
        List<Document> documents, List<Evidence> evidence, List<Relation> relations,
        List<Activity> activities, List<Context> contexts) {
    public record Identifier(String namespace, String value) {}
    public record Fact(String label, String value, List<String> evidenceIds) {}
    public record Tenure(String organizationId, String position, String party,
            LocalDate validFrom, LocalDate validUntil, Instant observedAt, List<String> evidenceIds) {}
    public record Entity(String id, String kind, String name, List<Identifier> identifiers,
            List<Fact> facts, List<Tenure> tenures) {}
    public record Mention(String id, String surface, int start, int end,
            List<String> candidatePersonIds, String personId, String decision) {}
    public record Segment(String id, String text, String locator, List<Mention> mentions) {}
    public record Document(String id, String version, String sourceKey, String recordKey,
            String sourceUrl, String title, String format, String bodyStatus, String licenseStatus,
            Instant publishedAt, Instant collectedAt, String rawStorageKey,
            String extractionVersion, List<Segment> segments, String observationId,
            String datePrecision, String transitionId, Instant observedAt) {
        public Document(String id, String version, String sourceKey, String recordKey,
                String sourceUrl, String title, String format, String bodyStatus, String licenseStatus,
                Instant publishedAt, Instant collectedAt, String rawStorageKey,
                String extractionVersion, List<Segment> segments, String observationId,
                String datePrecision, String transitionId) {
            this(id, version, sourceKey, recordKey, sourceUrl, title, format, bodyStatus, licenseStatus,
                    publishedAt, collectedAt, rawStorageKey, extractionVersion, segments, observationId, datePrecision, transitionId, null);
        }
        public Document(String id, String version, String sourceKey, String recordKey,
                String sourceUrl, String title, String format, String bodyStatus, String licenseStatus,
                Instant publishedAt, Instant collectedAt, String rawStorageKey,
                String extractionVersion, List<Segment> segments, String observationId, String datePrecision) {
            this(id, version, sourceKey, recordKey, sourceUrl, title, format, bodyStatus, licenseStatus,
                    publishedAt, collectedAt, rawStorageKey, extractionVersion, segments, observationId, datePrecision, null, null);
        }
    }
    public record Evidence(String id, String documentId, String documentVersion,
            String extractionVersion, String segmentId, int start, int end) {}
    public record Relation(String id, String subjectId, String objectId, String type,
            List<String> evidenceIds, String decision, String reason) {}
    public record Context(String eventId, String eventVersion, List<String> relationIds,
            List<String> evidenceIds, List<String> documentIds, String changeKind,
            Instant scheduledAt, String scheduledPrecision) {
        public Context(String eventId, String eventVersion, List<String> relationIds,
                List<String> evidenceIds, List<String> documentIds, String changeKind) {
            this(eventId,eventVersion,relationIds,evidenceIds,documentIds,changeKind,null,null);
        }
    }
}
