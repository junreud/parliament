package dev.parliament.service;

import dev.parliament.config.ParameterPlanStatus;
import dev.parliament.config.ParameterValueStrategy;
import dev.parliament.config.ParliamentIngestionProperties;
import dev.parliament.config.ParliamentParameterPlanCatalog;
import dev.parliament.config.ParliamentSourceCatalog;
import dev.parliament.config.ParliamentSourceDefinition;
import dev.parliament.persistence.IngestionHistoryEntry;
import dev.parliament.persistence.ParliamentIngestionHistoryRepository;
import org.springframework.scheduling.support.CronExpression;
import reactor.core.publisher.Mono;

import java.time.Clock;
import java.time.Instant;
import java.time.LocalDate;
import java.time.ZoneId;
import java.time.ZonedDateTime;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

public class ParliamentDashboardService {
    private final ParliamentIngestionHistoryRepository history;
    private final ParliamentSourceCatalog sources;
    private final ParliamentParameterPlanCatalog plans;
    private final ParliamentIngestionProperties properties;
    private final Clock clock;

    public ParliamentDashboardService(
            ParliamentIngestionHistoryRepository history,
            ParliamentSourceCatalog sources,
            ParliamentParameterPlanCatalog plans,
            ParliamentIngestionProperties properties,
            Clock clock
    ) {
        this.history = history;
        this.sources = sources;
        this.plans = plans;
        this.properties = properties;
        this.clock = clock;
    }

    public Mono<ParliamentDashboardSnapshot> snapshot(LocalDate selectedDate, int days) {
        if (days < 1 || days > 366) {
            return Mono.error(new IllegalArgumentException("days must be between 1 and 366"));
        }
        ZoneId zone = ZoneId.of(properties.getIncrementalZone());
        Instant now = clock.instant();
        LocalDate today = now.atZone(zone).toLocalDate();
        LocalDate selected = selectedDate == null ? today : selectedDate;
        LocalDate first = selected.minusDays(days - 1L);
        Instant from = first.atStartOfDay(zone).toInstant();
        Instant to = selected.plusDays(1).atStartOfDay(zone).toInstant();
        return history.findHistory(from, to).collectList()
                .map(entries -> build(entries, first, selected, today, now, zone));
    }

    private ParliamentDashboardSnapshot build(
            List<IngestionHistoryEntry> entries,
            LocalDate first,
            LocalDate selected,
            LocalDate today,
            Instant now,
            ZoneId zone
    ) {
        Map<LocalDate, Map<String, IngestionHistoryEntry>> latest = new HashMap<>();
        Map<LocalDate, List<IngestionHistoryEntry>> allByDay = new HashMap<>();
        for (IngestionHistoryEntry entry : entries) {
            Instant anchor = entry.scheduledFor() == null ? entry.runStartedAt() : entry.scheduledFor();
            LocalDate date = anchor.atZone(zone).toLocalDate();
            allByDay.computeIfAbsent(date, ignored -> new ArrayList<>()).add(entry);
            latest.computeIfAbsent(date, ignored -> new HashMap<>())
                    .merge(entry.sourceKey(), entry, this::newer);
        }

        List<DashboardDay> dayRows = new ArrayList<>();
        Map<LocalDate, List<DashboardSourceStatus>> sourceRowsByDay = new LinkedHashMap<>();
        for (LocalDate date = first; !date.isAfter(selected); date = date.plusDays(1)) {
            List<DashboardSourceStatus> statuses = statusesFor(
                    date, latest.getOrDefault(date, Map.of()), today, now, zone);
            sourceRowsByDay.put(date, statuses);
            DashboardOverview counts = count(statuses);
            dayRows.add(new DashboardDay(date, overall(counts), counts));
        }
        List<DashboardSourceStatus> selectedLatest = sourceRowsByDay.getOrDefault(selected, List.of());
        List<DashboardSourceStatus> selectedSources = detailStatusesFor(
                selected, allByDay.getOrDefault(selected, List.of()), today, now, zone);
        Instant next = properties.isAutomaticEnabled() ? nextSchedule(now, zone) : null;
        return new ParliamentDashboardSnapshot(
                now, zone.getId(), properties.isAutomaticEnabled(), next,
                count(selectedLatest), List.copyOf(dayRows), List.copyOf(selectedSources));
    }

    private List<DashboardSourceStatus> detailStatusesFor(
            LocalDate date,
            List<IngestionHistoryEntry> actualEntries,
            LocalDate today,
            Instant now,
            ZoneId zone
    ) {
        List<DashboardSourceStatus> details = actualEntries.stream()
                .map(this::actual)
                .collect(java.util.stream.Collectors.toCollection(ArrayList::new));
        java.util.Set<String> observed = actualEntries.stream()
                .map(IngestionHistoryEntry::sourceKey)
                .collect(java.util.stream.Collectors.toSet());
        sources.active().stream()
                .filter(source -> !observed.contains(source.key()))
                .map(source -> planned(source, date, today, now, zone))
                .forEach(details::add);
        details.sort(Comparator
                .comparing((DashboardSourceStatus status) -> priority(status.outcome()))
                .thenComparing(DashboardSourceStatus::sourceName)
                .thenComparing(status -> status.runId() == null ? Long.MAX_VALUE : status.runId()));
        return details;
    }

    private List<DashboardSourceStatus> statusesFor(
            LocalDate date,
            Map<String, IngestionHistoryEntry> actual,
            LocalDate today,
            Instant now,
            ZoneId zone
    ) {
        List<DashboardSourceStatus> statuses = new ArrayList<>();
        for (ParliamentSourceDefinition source : sources.active()) {
            IngestionHistoryEntry entry = actual.get(source.key());
            if (entry == null) {
                statuses.add(planned(source, date, today, now, zone));
            } else {
                statuses.add(actual(entry));
            }
        }
        statuses.sort(Comparator
                .comparing((DashboardSourceStatus status) -> priority(status.outcome()))
                .thenComparing(DashboardSourceStatus::sourceName));
        return statuses;
    }

    private DashboardSourceStatus planned(
            ParliamentSourceDefinition source,
            LocalDate date,
            LocalDate today,
            Instant now,
            ZoneId zone
    ) {
        Instant scheduledFor = scheduledOn(date, zone);
        IngestionSourceOutcome outcome;
        if (!properties.isAutomaticEnabled()) {
            outcome = IngestionSourceOutcome.AUTOMATION_DISABLED;
        } else if (date.isAfter(today) || scheduledFor != null && scheduledFor.isAfter(now)) {
            outcome = IngestionSourceOutcome.SCHEDULED;
        } else {
            outcome = IngestionSourceOutcome.MISSED;
        }
        return new DashboardSourceStatus(
                null, source.key(), source.apiCode(), source.name(), expectation(source), outcome,
                IngestionTrigger.AUTOMATIC, scheduledFor, null, null,
                0, 0, 0, 0, 0, 0, null, null);
    }

    private DashboardSourceStatus actual(IngestionHistoryEntry entry) {
        return new DashboardSourceStatus(
                entry.runId(), entry.sourceKey(), entry.apiCode(), entry.sourceName(),
                entry.expectation(), entry.outcome(), entry.trigger(), entry.scheduledFor(),
                entry.sourceStartedAt(), entry.sourceFinishedAt(), entry.variants(), entry.scanned(),
                entry.changed(), entry.unchanged(), entry.removed(), entry.pages(),
                entry.errorCode(), entry.message());
    }

    private IngestionExpectation expectation(ParliamentSourceDefinition source) {
        return plans.find(source.key()).map(plan -> {
            if (plan.status() == ParameterPlanStatus.EMPTY_ALLOWED) {
                return IngestionExpectation.EMPTY_ALLOWED;
            }
            if (plan.status() == ParameterPlanStatus.RETRYABLE) {
                return IngestionExpectation.RETRYABLE;
            }
            if (plan.status() == ParameterPlanStatus.PARAMETERIZED) {
                boolean dependency = plan.bindings().stream()
                        .anyMatch(binding -> binding.strategy() == ParameterValueStrategy.SOURCE_FIELD);
                return dependency ? IngestionExpectation.DEPENDENCY_DRIVEN
                        : IngestionExpectation.PARAMETERIZED_STATIC;
            }
            return IngestionExpectation.STANDARD;
        }).orElse(IngestionExpectation.STANDARD);
    }

    private DashboardOverview count(List<DashboardSourceStatus> statuses) {
        return new DashboardOverview(
                statuses.size(), occurrences(statuses, IngestionSourceOutcome.SCHEDULED),
                occurrences(statuses, IngestionSourceOutcome.RUNNING),
                occurrences(statuses, IngestionSourceOutcome.SUCCESS_CHANGED),
                occurrences(statuses, IngestionSourceOutcome.SUCCESS_UNCHANGED),
                occurrences(statuses, IngestionSourceOutcome.SUCCESS_EMPTY),
                occurrences(statuses, IngestionSourceOutcome.SKIPPED_NO_PARENT_CHANGES),
                occurrences(statuses, IngestionSourceOutcome.PARTIAL),
                occurrences(statuses, IngestionSourceOutcome.FAILED),
                occurrences(statuses, IngestionSourceOutcome.RETRY_EXHAUSTED),
                occurrences(statuses, IngestionSourceOutcome.MISSED),
                occurrences(statuses, IngestionSourceOutcome.AUTOMATION_DISABLED));
    }

    private int occurrences(List<DashboardSourceStatus> statuses, IngestionSourceOutcome outcome) {
        return (int) statuses.stream().filter(status -> status.outcome() == outcome).count();
    }

    private String overall(DashboardOverview counts) {
        if (counts.failed() + counts.retryExhausted() + counts.partial() + counts.missed() > 0) {
            return "ATTENTION";
        }
        if (counts.running() > 0) {
            return "RUNNING";
        }
        if (counts.scheduled() > 0) {
            return "SCHEDULED";
        }
        if (counts.automationDisabled() == counts.expected() && counts.expected() > 0) {
            return "AUTOMATION_DISABLED";
        }
        return "HEALTHY";
    }

    private IngestionHistoryEntry newer(IngestionHistoryEntry left, IngestionHistoryEntry right) {
        Instant leftAt = left.sourceStartedAt() == null ? left.runStartedAt() : left.sourceStartedAt();
        Instant rightAt = right.sourceStartedAt() == null ? right.runStartedAt() : right.sourceStartedAt();
        return rightAt.isAfter(leftAt) ? right : left;
    }

    private Instant nextSchedule(Instant now, ZoneId zone) {
        ZonedDateTime next = cron().next(now.atZone(zone));
        return next == null ? null : next.toInstant();
    }

    private Instant scheduledOn(LocalDate date, ZoneId zone) {
        ZonedDateTime next = cron().next(date.atStartOfDay(zone).minusSeconds(1));
        return next != null && next.toLocalDate().equals(date) ? next.toInstant() : null;
    }

    private CronExpression cron() {
        return CronExpression.parse(properties.getIncrementalCron());
    }

    private int priority(IngestionSourceOutcome outcome) {
        return switch (outcome) {
            case RETRY_EXHAUSTED, FAILED, PARTIAL, MISSED -> 0;
            case RUNNING -> 1;
            case SCHEDULED -> 2;
            case SUCCESS_CHANGED -> 3;
            case SUCCESS_UNCHANGED, SUCCESS_EMPTY, SKIPPED_NO_PARENT_CHANGES -> 4;
            case AUTOMATION_DISABLED -> 5;
        };
    }
}
