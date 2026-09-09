package dev.parliament.service;

import java.time.LocalDate;

public record DashboardDay(
        LocalDate date,
        String overall,
        DashboardOverview counts
) {
}
