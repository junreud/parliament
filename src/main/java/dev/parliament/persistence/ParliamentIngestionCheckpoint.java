package dev.parliament.persistence;

public record ParliamentIngestionCheckpoint(int nextPage, boolean complete) {
    public static ParliamentIngestionCheckpoint initial() {
        return new ParliamentIngestionCheckpoint(1, false);
    }
}
