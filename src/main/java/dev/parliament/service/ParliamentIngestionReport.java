package dev.parliament.service;

import java.util.List;

public record ParliamentIngestionReport(
        boolean writePerformed,
        List<ParliamentSourceReport> sources
) {
    public ParliamentIngestionReport {
        sources = List.copyOf(sources);
    }
}

