package dev.parliament.service;

import java.time.Instant;
import java.util.List;

public record ParliamentSyncReport(
        Instant startedAt,
        Instant finishedAt,
        List<ParliamentSyncSourceReport> sources
) {
    public ParliamentSyncReport {
        sources = List.copyOf(sources);
    }
}
