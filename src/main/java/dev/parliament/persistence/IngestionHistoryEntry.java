package dev.parliament.persistence;

import dev.parliament.service.IngestionExpectation;
import dev.parliament.service.IngestionRunStatus;
import dev.parliament.service.IngestionSourceOutcome;
import dev.parliament.service.IngestionTrigger;

import java.time.Instant;

public record IngestionHistoryEntry(
        long runId,
        IngestionTrigger trigger,
        Instant scheduledFor,
        Instant runStartedAt,
        IngestionRunStatus runStatus,
        String sourceKey,
        String apiCode,
        String sourceName,
        IngestionExpectation expectation,
        IngestionSourceOutcome outcome,
        Instant sourceStartedAt,
        Instant sourceFinishedAt,
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
