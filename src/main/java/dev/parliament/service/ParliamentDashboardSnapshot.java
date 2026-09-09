package dev.parliament.service;

import java.time.Instant;
import java.util.List;

public record ParliamentDashboardSnapshot(
        Instant generatedAt,
        String timezone,
        boolean automaticEnabled,
        Instant nextScheduledAt,
        DashboardOverview overview,
        List<DashboardDay> days,
        List<DashboardSourceStatus> sources
) {
}
