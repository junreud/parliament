package dev.parliament.persistence;

import dev.parliament.service.IngestionExpectation;

public record IngestionSourceSchedule(
        String sourceKey,
        String apiCode,
        String sourceName,
        IngestionExpectation expectation
) {
}
