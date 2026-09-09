package dev.parliament.controller;

import dev.parliament.config.ParliamentIngestionProperties;
import dev.parliament.service.DashboardOverview;
import dev.parliament.service.ParliamentDashboardService;
import dev.parliament.service.ParliamentDashboardSnapshot;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import org.springframework.web.server.ResponseStatusException;
import reactor.core.publisher.Mono;
import reactor.test.StepVerifier;

import java.time.Instant;
import java.time.LocalDate;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class ParliamentDashboardControllerTest {

    @Test
    void protectsDashboardDataWithAdminKeyAndDelegatesValidatedRange() {
        ParliamentDashboardService service = mock(ParliamentDashboardService.class);
        ParliamentIngestionProperties properties = new ParliamentIngestionProperties();
        properties.setAdminKey("admin-key");
        ParliamentDashboardController controller = new ParliamentDashboardController(service, properties);
        LocalDate date = LocalDate.of(2026, 9, 10);
        ParliamentDashboardSnapshot snapshot = new ParliamentDashboardSnapshot(
                Instant.EPOCH, "Asia/Seoul", false, null,
                new DashboardOverview(0, 0, 0, 0, 0, 0, 0, 0, 0),
                List.of(), List.of());
        when(service.snapshot(date, 30)).thenReturn(Mono.just(snapshot));

        assertThatThrownBy(() -> controller.snapshot("wrong", date, 30))
                .isInstanceOfSatisfying(ResponseStatusException.class,
                        error -> org.assertj.core.api.Assertions.assertThat(error.getStatusCode())
                                .isEqualTo(HttpStatus.FORBIDDEN));
        StepVerifier.create(controller.snapshot("admin-key", date, 30))
                .expectNext(snapshot)
                .verifyComplete();
        verify(service).snapshot(date, 30);
    }
}
