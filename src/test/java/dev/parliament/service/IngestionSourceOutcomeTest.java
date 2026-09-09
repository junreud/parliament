package dev.parliament.service;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class IngestionSourceOutcomeTest {

    @Test
    void separatesChangedUnchangedEmptySkippedPartialFailedAndRetryExhausted() {
        assertThat(IngestionSourceOutcome.from(report(3, 2, 1, true, false, null)))
                .isEqualTo(IngestionSourceOutcome.SUCCESS_CHANGED);
        assertThat(IngestionSourceOutcome.from(report(3, 0, 3, true, false, null)))
                .isEqualTo(IngestionSourceOutcome.SUCCESS_UNCHANGED);
        assertThat(IngestionSourceOutcome.from(report(0, 0, 0, true, false, null)))
                .isEqualTo(IngestionSourceOutcome.SUCCESS_EMPTY);
        assertThat(IngestionSourceOutcome.from(new ParliamentSyncSourceReport(
                "source", 0, 0, 0, 0, 0, 0, true,
                ParliamentSourceStatus.COMPLETE, "no changed parent identifiers", false)))
                .isEqualTo(IngestionSourceOutcome.SKIPPED_NO_PARENT_CHANGES);
        assertThat(IngestionSourceOutcome.from(new ParliamentSyncSourceReport(
                "source", 1, 3, 1, 2, 0, 1, false,
                ParliamentSourceStatus.PARTIAL, null, false)))
                .isEqualTo(IngestionSourceOutcome.PARTIAL);
        assertThat(IngestionSourceOutcome.from(new ParliamentSyncSourceReport(
                "source", 1, 0, 0, 0, 0, 0, false,
                ParliamentSourceStatus.FAILED, "bad response", false)))
                .isEqualTo(IngestionSourceOutcome.FAILED);
        assertThat(IngestionSourceOutcome.from(new ParliamentSyncSourceReport(
                "source", 1, 0, 0, 0, 0, 0, false,
                ParliamentSourceStatus.FAILED, "retries exhausted", true)))
                .isEqualTo(IngestionSourceOutcome.RETRY_EXHAUSTED);
    }

    private ParliamentSyncSourceReport report(
            int scanned, int changed, int unchanged, boolean complete,
            boolean retryExhausted, String message
    ) {
        return new ParliamentSyncSourceReport(
                "source", 1, scanned, changed, unchanged, 0, 1, complete,
                complete ? ParliamentSourceStatus.COMPLETE : ParliamentSourceStatus.FAILED,
                message, retryExhausted);
    }
}
