package dev.parliament.persistence;

import dev.parliament.service.IngestionSourceOutcome;

import java.time.Instant;

public record IngestionSourceCompletion(
        IngestionSourceOutcome outcome,
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
