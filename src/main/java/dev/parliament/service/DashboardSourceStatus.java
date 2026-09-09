package dev.parliament.service;

import java.time.Instant;

public record DashboardSourceStatus(
        Long runId,
        String sourceKey,
        String apiCode,
        String sourceName,
        IngestionExpectation expectation,
        IngestionSourceOutcome outcome,
        IngestionTrigger trigger,
        Instant scheduledFor,
        Instant startedAt,
        Instant finishedAt,
        int variants,
        int scanned,
        int changed,
        int unchanged,
        int removed,
        int pages,
        String errorCode,
        String message
) {
}
