package dev.parliament.controller;

import dev.parliament.config.ParliamentIngestionProperties;
import dev.parliament.service.ParliamentIngestionReport;
import dev.parliament.service.ParliamentIngestionRequest;
import dev.parliament.service.ParliamentIngestionService;
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

import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class ParliamentIngestionControllerTest {
    @Mock private ParliamentIngestionService service;

    private ParliamentIngestionController controller;
    private ParliamentIngestionRequest request;

    @BeforeEach
    void setUp() {
        ParliamentIngestionProperties properties = new ParliamentIngestionProperties();
        properties.setAdminKey("admin-key");
        controller = new ParliamentIngestionController(service, properties);
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
}

