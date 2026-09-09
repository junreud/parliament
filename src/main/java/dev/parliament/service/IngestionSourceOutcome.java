package dev.parliament.service;

public enum IngestionSourceOutcome {
    SCHEDULED,
    RUNNING,
    SUCCESS_CHANGED,
    SUCCESS_UNCHANGED,
    SUCCESS_EMPTY,
    SKIPPED_NO_PARENT_CHANGES,
    PARTIAL,
    FAILED,
    RETRY_EXHAUSTED,
    MISSED,
    AUTOMATION_DISABLED;

    public static IngestionSourceOutcome from(ParliamentSyncSourceReport report) {
        if (report.retryExhausted()) {
            return RETRY_EXHAUSTED;
        }
        if (report.status() == ParliamentSourceStatus.FAILED) {
            return FAILED;
        }
        if (report.status() == ParliamentSourceStatus.PARTIAL || !report.complete()) {
            return PARTIAL;
        }
        if (report.variants() == 0 && "no changed parent identifiers".equals(report.message())) {
            return SKIPPED_NO_PARENT_CHANGES;
        }
        if (report.scanned() == 0) {
            return SUCCESS_EMPTY;
        }
        if (report.changed() > 0 || report.removed() > 0) {
            return SUCCESS_CHANGED;
        }
        return SUCCESS_UNCHANGED;
    }

    public boolean isFailure() {
        return this == FAILED || this == RETRY_EXHAUSTED || this == PARTIAL || this == MISSED;
    }

    public boolean isSuccess() {
        return this == SUCCESS_CHANGED || this == SUCCESS_UNCHANGED
                || this == SUCCESS_EMPTY || this == SKIPPED_NO_PARENT_CHANGES;
    }
}
