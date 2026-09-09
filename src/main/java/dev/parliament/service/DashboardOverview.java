package dev.parliament.service;

public record DashboardOverview(
        int expected,
        int scheduled,
        int running,
        int successChanged,
        int successUnchanged,
        int successEmpty,
        int skippedNoParentChanges,
        int partial,
        int failed,
        int retryExhausted,
        int missed,
        int automationDisabled
) {
}
