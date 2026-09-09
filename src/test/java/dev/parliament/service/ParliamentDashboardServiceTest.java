package dev.parliament.service;

import dev.parliament.config.ParameterPlanStatus;
import dev.parliament.config.ParliamentCollectionMode;
import dev.parliament.config.ParliamentIngestionProperties;
import dev.parliament.config.ParliamentMediaType;
import dev.parliament.config.ParliamentParameterPlan;
import dev.parliament.config.ParliamentParameterPlanCatalog;
import dev.parliament.config.ParliamentSourceCatalog;
import dev.parliament.config.ParliamentSourceDefinition;
import dev.parliament.persistence.IngestionHistoryEntry;
import dev.parliament.persistence.ParliamentIngestionHistoryRepository;
import org.junit.jupiter.api.Test;
import reactor.core.publisher.Flux;
import reactor.test.StepVerifier;

import java.time.Clock;
import java.time.Instant;
import java.time.LocalDate;
import java.time.ZoneOffset;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

class ParliamentDashboardServiceTest {

    @Test
    void overlaysActualHistoryOnEveryExpectedSourceAndMarksMissingRuns() {
        ParliamentSourceDefinition standard = source("standard", "일반 API");
        ParliamentSourceDefinition empty = source("empty", "빈 결과 허용 API");
        ParliamentSourceCatalog sources = ParliamentSourceCatalog.of(List.of(standard, empty));
        ParliamentParameterPlanCatalog plans = ParliamentParameterPlanCatalog.of(List.of(
                new ParliamentParameterPlan("empty", "official-1", ParameterPlanStatus.EMPTY_ALLOWED, List.of())));
        ParliamentIngestionProperties properties = new ParliamentIngestionProperties();
        properties.setAutomaticEnabled(true);
        properties.setIncrementalCron("0 0 4 * * *");
        properties.setIncrementalZone("Asia/Seoul");
        ParliamentIngestionHistoryRepository history = mock(ParliamentIngestionHistoryRepository.class);
        Instant scheduled = Instant.parse("2026-09-09T20:00:00Z");
        when(history.findHistory(any(), any())).thenReturn(Flux.just(
                entry(1, "standard", "일반 API", IngestionExpectation.STANDARD,
                        IngestionSourceOutcome.SUCCESS_CHANGED, Instant.parse("2026-09-08T19:00:00Z")),
                entry(2, "empty", "빈 결과 허용 API", IngestionExpectation.EMPTY_ALLOWED,
                        IngestionSourceOutcome.FAILED, Instant.parse("2026-09-09T19:00:00Z")),
                entry(3, "empty", "빈 결과 허용 API", IngestionExpectation.EMPTY_ALLOWED,
                        IngestionSourceOutcome.SUCCESS_EMPTY, scheduled)));
        Clock clock = Clock.fixed(Instant.parse("2026-09-09T21:00:00Z"), ZoneOffset.UTC);

        ParliamentDashboardService service = new ParliamentDashboardService(
                history, sources, plans, properties, clock);

        StepVerifier.create(service.snapshot(LocalDate.of(2026, 9, 10), 2))
                .assertNext(snapshot -> {
                    assertThat(snapshot.automaticEnabled()).isTrue();
                    assertThat(snapshot.overview().expected()).isEqualTo(2);
                    assertThat(snapshot.overview().successEmpty()).isEqualTo(1);
                    assertThat(snapshot.overview().missed()).isEqualTo(1);
                    assertThat(snapshot.overview().failed()).isZero();
                    assertThat(snapshot.days()).hasSize(2);
                    assertThat(snapshot.sources()).extracting(DashboardSourceStatus::outcome)
                            .containsExactlyInAnyOrder(
                                    IngestionSourceOutcome.MISSED,
                                    IngestionSourceOutcome.FAILED,
                                    IngestionSourceOutcome.SUCCESS_EMPTY);
                })
                .verifyComplete();
    }

    @Test
    void validatesRequestedHistoryWindow() {
        ParliamentIngestionHistoryRepository history = mock(ParliamentIngestionHistoryRepository.class);
        ParliamentDashboardService service = new ParliamentDashboardService(
                history, ParliamentSourceCatalog.of(List.of()),
                ParliamentParameterPlanCatalog.of(List.of()),
                new ParliamentIngestionProperties(), Clock.systemUTC());

        StepVerifier.create(service.snapshot(LocalDate.of(2026, 9, 10), 0))
                .expectErrorMatches(error -> error instanceof IllegalArgumentException
                        && error.getMessage().contains("between 1 and 366"))
                .verify();
    }

    private ParliamentSourceDefinition source(String key, String name) {
        return new ParliamentSourceDefinition(
                key, key, name, null, ParliamentMediaType.DATA,
                ParliamentCollectionMode.PAGE, Map.of());
    }

    private IngestionHistoryEntry entry(
            long runId, String sourceKey, String sourceName,
            IngestionExpectation expectation, IngestionSourceOutcome outcome,
            Instant scheduledFor
    ) {
        return new IngestionHistoryEntry(
                runId, IngestionTrigger.AUTOMATIC, scheduledFor, scheduledFor,
                IngestionRunStatus.SUCCESS, sourceKey, sourceKey, sourceName,
                expectation, outcome, scheduledFor, scheduledFor.plusSeconds(10),
                1, outcome == IngestionSourceOutcome.SUCCESS_EMPTY ? 0 : 1,
                outcome == IngestionSourceOutcome.SUCCESS_CHANGED ? 1 : 0,
                0, 0, 1, null, null);
    }
}
