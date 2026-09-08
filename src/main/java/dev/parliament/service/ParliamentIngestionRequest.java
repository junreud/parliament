package dev.parliament.service;

import java.util.List;

public record ParliamentIngestionRequest(
        List<String> sourceKeys,
        int pageSize,
        int maxPages,
        boolean confirmWrite
) {
    public ParliamentIngestionRequest {
        sourceKeys = sourceKeys == null ? List.of() : List.copyOf(sourceKeys);
    }
}

