package dev.parliament.service;

public record ParliamentSyncSourceReport(
        String sourceKey,
        int variants,
        int scanned,
        int changed,
        int unchanged,
        int removed,
        int pages,
        boolean complete,
        ParliamentSourceStatus status,
        String message
) {
}
