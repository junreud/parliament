package dev.parliament.metrics;

import dev.parliament.tracking.TrackingAdminAuthorization;
import dev.parliament.tracking.TrackingAuthPolicy;
import dev.parliament.tracking.TrackingAuthRepository;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.test.web.reactive.server.WebTestClient;
import reactor.core.publisher.Mono;
import reactor.test.StepVerifier;
import java.time.Instant;
import java.util.Map;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

class UsageControllerTest {
    private UsageRepository repository;
    private TrackingAuthRepository auth;
    private WebTestClient client;

    @BeforeEach
    void setup() {
        repository = mock(UsageRepository.class);
        auth = mock(TrackingAuthRepository.class);
        when(auth.current(any())).thenReturn(Mono.empty());
        when(auth.current("valid-session")).thenReturn(Mono.just(
                new TrackingAuthRepository.Session("valid-session", "user", "csrf", "weekly")));
        client = WebTestClient.bindToController(new UsageController(repository, auth,
                new TrackingAuthPolicy("http://localhost:3000"),
                new TrackingAdminAuthorization("test-admin"))).build();
    }

    @Test
    void requiresVerifiedSessionAndSameOriginCsrfForUsage() {
        client.post().uri("/api/v1/usage").bodyValue(Map.of("event", "activity_opened"))
                .exchange().expectStatus().isUnauthorized();
        client.post().uri("/api/v1/usage").cookie("parliament_session", "valid-session")
                .header("Origin", "https://untrusted.example").header("X-CSRF-Token", "csrf")
                .bodyValue(Map.of("event", "activity_opened"))
                .exchange().expectStatus().isForbidden();
        client.post().uri("/api/v1/usage").cookie("parliament_session", "valid-session")
                .header("Origin", "http://localhost:3000").header("X-CSRF-Token", "wrong")
                .bodyValue(Map.of("event", "activity_opened"))
                .exchange().expectStatus().isForbidden();
        verifyNoInteractions(repository);

        when(repository.record(eq("user"), eq("activity_opened"), isNull(), any()))
                .thenReturn(Mono.empty());
        client.post().uri("/api/v1/usage").cookie("parliament_session", "valid-session")
                .header("Origin", "http://localhost:3000").header("X-CSRF-Token", "csrf")
                .bodyValue(Map.of("event", "activity_opened"))
                .exchange().expectStatus().isAccepted().expectHeader().valueEquals("Cache-Control", "no-store");
    }

    @Test
    void aggregateReportRequiresAdminKey() {
        String path = "/admin/tracking/metrics?from=2026-09-01T00:00:00Z&to=2026-10-01T00:00:00Z";
        client.get().uri(path).exchange().expectStatus().isForbidden();
        verifyNoInteractions(repository);
        when(repository.report(any(), any(), any())).thenReturn(Mono.just(
                new UsageRepository.Report(0, 0, 0, null, 0, 0)));
        client.get().uri(path).header("X-Parliament-Ingestion-Key", "test-admin")
                .exchange().expectStatus().isOk().expectBody().jsonPath("$.activated").isEqualTo(0);
    }

    @Test
    void rejectsMissingUnknownOrMalformedMeasurementBeforeDatabaseAccess() {
        UsageRepository checked = new UsageRepository(null);
        StepVerifier.create(checked.record("user", null, null, Instant.EPOCH))
                .expectError(IllegalArgumentException.class).verify();
        StepVerifier.create(checked.record("user", "political_target", null, Instant.EPOCH))
                .expectError(IllegalArgumentException.class).verify();
        StepVerifier.create(checked.record("user", "relevance", null, Instant.EPOCH))
                .expectError(IllegalArgumentException.class).verify();
        StepVerifier.create(checked.report(Instant.EPOCH, Instant.EPOCH, Instant.EPOCH))
                .expectError(IllegalArgumentException.class).verify();
    }
}
