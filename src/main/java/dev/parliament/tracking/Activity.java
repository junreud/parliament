package dev.parliament.tracking;

import java.time.Instant;
import java.util.List;

/** A public, source-grounded activity. Imported versions are immutable. */
public record Activity(
        String id,
        String type,
        String title,
        String summary,
        String stage,
        List<String> personIds,
        List<String> topics,
        String billId,
        Instant occurredAt,
        Instant publishedAt,
        Instant collectedAt,
        String sourceUrl,
        List<Evidence> evidence,
        List<Vote> votes,
        String coverage,
        boolean corrected,
        String version,
        Instant changedAt) {
    public Activity(
            String id,
            String type,
            String title,
            String summary,
            String stage,
            List<String> personIds,
            List<String> topics,
            String billId,
            Instant occurredAt,
            Instant publishedAt,
            Instant collectedAt,
            String sourceUrl,
            List<Evidence> evidence,
            List<Vote> votes,
            String coverage,
            boolean corrected,
            String version) {
        this(
                id,
                type,
                title,
                summary,
                stage,
                personIds,
                topics,
                billId,
                occurredAt,
                publishedAt,
                collectedAt,
                sourceUrl,
                evidence,
                votes,
                coverage,
                corrected,
                version,
                null);
    }

    public Activity visible(Instant at, boolean correction) {
        return new Activity(
                id,
                type,
                title,
                summary,
                stage,
                personIds,
                topics,
                billId,
                occurredAt,
                publishedAt,
                collectedAt,
                sourceUrl,
                evidence,
                votes,
                coverage,
                correction,
                version,
                at);
    }

    public record Evidence(
            String id, String sourceUrl, String excerpt, String locator, String sourceVersion) {}

    public record Vote(String personId, String name, String result, String sessionId) {}

    public Activity explained(String explanation, boolean correction) {
        return new Activity(
                id,
                type,
                title,
                explanation,
                stage,
                personIds,
                topics,
                billId,
                occurredAt,
                publishedAt,
                collectedAt,
                sourceUrl,
                evidence,
                votes,
                coverage,
                correction,
                version,
                changedAt);
    }
}
