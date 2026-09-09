package dev.parliament.controller;

import dev.parliament.config.ParliamentIngestionProperties;
import dev.parliament.service.ParliamentIngestionReport;
import dev.parliament.service.ParliamentIngestionRequest;
import dev.parliament.service.ParliamentIngestionService;
import dev.parliament.service.ParliamentSocialVerificationService;
import dev.parliament.service.ParliamentJobGuard;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.http.HttpStatus;
import org.springframework.web.server.ResponseStatusException;
import reactor.core.publisher.Mono;
import reactor.test.StepVerifier;

import java.util.List;
import java.time.Instant;

import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class ParliamentIngestionControllerTest {
    @Mock private ParliamentIngestionService service;
    @Mock private ParliamentSocialVerificationService socialVerificationService;

    private ParliamentIngestionController controller;
    private ParliamentIngestionRequest request;

    @BeforeEach
    void setUp() {
        ParliamentIngestionProperties properties = new ParliamentIngestionProperties();
        properties.setAdminKey("admin-key");
        controller = new ParliamentIngestionController(
                service, socialVerificationService, new ParliamentJobGuard(), properties);
        request = new ParliamentIngestionRequest(List.of("allnamember"), 10, 1, false);
    }

    @Test
    void rejectsInvalidAdminKeyBeforeCallingService() {
        assertThatThrownBy(() -> controller.preflight("wrong", request))
                .isInstanceOfSatisfying(ResponseStatusException.class,
                        error -> org.assertj.core.api.Assertions.assertThat(error.getStatusCode())
                                .isEqualTo(HttpStatus.FORBIDDEN));
    }

    @Test
    void delegatesPreflightAndMapsValidationErrors() {
        when(service.preflight(request)).thenReturn(Mono.just(new ParliamentIngestionReport(false, List.of())));

        StepVerifier.create(controller.preflight("admin-key", request))
                .expectNextMatches(report -> !report.writePerformed())
                .verifyComplete();
        verify(service).preflight(request);

        when(service.run(request)).thenReturn(Mono.error(new IllegalArgumentException("invalid")));
        StepVerifier.create(controller.run("admin-key", request))
                .expectErrorMatches(error -> error instanceof ResponseStatusException response
                        && response.getStatusCode().equals(HttpStatus.BAD_REQUEST))
                .verify();
    }

    @Test
    void mapsSynchronousValidationErrorsToBadRequest() {
        when(service.preflight(request)).thenThrow(new IllegalArgumentException("invalid request"));

        StepVerifier.create(controller.preflight("admin-key", request))
                .expectErrorMatches(error -> error instanceof ResponseStatusException response
                        && response.getStatusCode().equals(HttpStatus.BAD_REQUEST))
                .verify();
    }

    @Test
    void rejectsConcurrentIngestionRuns() {
        when(service.run(request)).thenReturn(Mono.never());
        var firstRun = controller.run("admin-key", request).subscribe();

        StepVerifier.create(controller.run("admin-key", request))
                .expectErrorMatches(error -> error instanceof ResponseStatusException response
                        && response.getStatusCode().equals(HttpStatus.CONFLICT))
                .verify();

        firstRun.dispose();
    }

    @Test
    void exposesManualIncrementalSyncAndSocialVerificationBehindTheAdminKey() {
        ParliamentIngestionRequest syncRequest = new ParliamentIngestionRequest(
                List.of("allnamember"), 10, 1, true);
        var syncReport = new dev.parliament.service.ParliamentSyncReport(
                Instant.EPOCH, Instant.EPOCH, List.of());
        when(service.synchronize(syncRequest)).thenReturn(Mono.just(syncReport));
        when(socialVerificationService.verifyDue(java.time.Duration.ofDays(7), 20))
                .thenReturn(Mono.just(12));

        StepVerifier.create(controller.synchronize("admin-key", syncRequest))
                .expectNext(syncReport)
                .verifyComplete();
        StepVerifier.create(controller.verifySocial("admin-key", 7, 20))
                .expectNext(12)
                .verifyComplete();

        verify(service).synchronize(syncRequest);
        verify(socialVerificationService).verifyDue(java.time.Duration.ofDays(7), 20);
    }
}
