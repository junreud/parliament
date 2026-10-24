package dev.parliament.beta;

import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.Map;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.test.web.reactive.server.WebTestClient;
import org.springframework.web.server.ResponseStatusException;
import org.springframework.http.HttpStatus;
import reactor.core.publisher.Mono;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

class BetaControllerTest {
    private BetaRepository repository;
    private WebTestClient client;
    private static final String TOKEN = "a".repeat(43);
    private static final Instant NOW = Instant.parse("2026-10-17T00:00:00Z");

    @BeforeEach
    void setup() {
        repository = mock(BetaRepository.class);
        when(repository.current(any(), any())).thenReturn(Mono.empty());
        when(repository.current(eq(TOKEN), any())).thenReturn(Mono.just(
                new BetaRepository.Session("pseudonym", "csrf", NOW.plus(BetaPolicy.RETENTION))));
        client = WebTestClient.bindToController(new BetaController(repository,
                new BetaPolicy("http://localhost:3000"), new BetaRateLimiter(),
                Clock.fixed(NOW, ZoneOffset.UTC), "test-admin")).build();
    }

    @Test
    void absentSessionDoesNotCreateParticipantOrCookie() {
        client.get().uri("/api/v1/beta/session").exchange().expectStatus().isOk()
                .expectHeader().valueEquals("Cache-Control", "no-store")
                .expectCookie().doesNotExist("parliament_beta")
                .expectBody().jsonPath("$.participating").isEqualTo(false)
                .jsonPath("$.csrfToken").doesNotExist();
    }

    @Test
    void enrollRequiresOriginAndConsentAndReturnsOnlyOpaqueSession() {
        Map<String, Object> body = Map.of("email", "beta@example.org", "consent", true,
                "cohort", "external", "source", "instagram");
        client.post().uri("/api/v1/beta/participants").bodyValue(body).exchange()
                .expectStatus().isForbidden();
        client.post().uri("/api/v1/beta/participants").header("Origin", "http://localhost:3000")
                .bodyValue(Map.of("email", "beta@example.org", "consent", false,
                        "cohort", "external", "source", "instagram")).exchange().expectStatus().isBadRequest();
        verifyNoInteractions(repository);
        when(repository.enroll(any(), any())).thenReturn(Mono.just(new BetaRepository.Enrolled(TOKEN, "csrf")));
        client.post().uri("/api/v1/beta/participants").header("Origin", "http://localhost:3000")
                .bodyValue(body).exchange().expectStatus().isCreated()
                .expectCookie().httpOnly("parliament_beta", true)
                .expectCookie().sameSite("parliament_beta", "Strict")
                .expectBody().jsonPath("$.participating").isEqualTo(true)
                .jsonPath("$.csrfToken").isEqualTo("csrf")
                .jsonPath("$.email").doesNotExist().jsonPath("$.participantId").doesNotExist();
    }

    @Test
    void repeatedEnrollmentWithValidCookieKeepsExistingParticipant() {
        client.post().uri("/api/v1/beta/participants").cookie("parliament_beta", TOKEN)
                .header("Origin", "http://localhost:3000")
                .bodyValue(Map.of("email", "beta@example.org", "consent", true,
                        "cohort", "external", "source", "direct"))
                .exchange().expectStatus().isCreated().expectBody()
                .jsonPath("$.csrfToken").isEqualTo("csrf");
        verify(repository, never()).enroll(any(), any());
    }

    @Test
    void sharedProxyAllowsElevenDifferentValidEnrollmentAddresses() {
        when(repository.enroll(any(), any())).thenReturn(Mono.just(new BetaRepository.Enrolled(TOKEN, "csrf")));
        for (int index = 0; index < 11; index++) {
            client.post().uri("/api/v1/beta/participants").header("Origin", "http://localhost:3000")
                    .bodyValue(Map.of("email", "different" + index + "@example.org", "consent", true,
                            "cohort", "external", "source", "instagram"))
                    .exchange().expectStatus().isCreated();
        }
    }

    @Test
    void invalidFormsDoNotConsumeEnrollmentQuotaAndNormalizedAddressRepeatsAreLimited() {
        when(repository.enroll(any(), any())).thenReturn(Mono.just(new BetaRepository.Enrolled(TOKEN, "csrf")));
        for (int index = 0; index < 20; index++) {
            client.post().uri("/api/v1/beta/participants").header("Origin", "http://localhost:3000")
                    .bodyValue(Map.of("email", "invalid", "consent", false,
                            "cohort", "external", "source", "instagram"))
                    .exchange().expectStatus().isBadRequest();
        }
        for (int index = 0; index < 5; index++) {
            client.post().uri("/api/v1/beta/participants").header("Origin", "http://localhost:3000")
                    .bodyValue(Map.of("email", index % 2 == 0 ? " Same@EXAMPLE.ORG " : "same@example.org",
                            "consent", true, "cohort", "external", "source", "instagram"))
                    .exchange().expectStatus().isCreated();
        }
        client.post().uri("/api/v1/beta/participants").header("Origin", "http://localhost:3000")
                .bodyValue(Map.of("email", "same@example.org", "consent", true,
                        "cohort", "external", "source", "instagram"))
                .exchange().expectStatus().isEqualTo(429);
        verify(repository, times(5)).enroll(any(), any());
    }

    @Test
    void reportRejectsPartialKoreanDaysBeforeDatabaseAccess() {
        WebTestClient checked = WebTestClient.bindToController(new BetaController(
                new BetaRepository(null, null, new BetaPolicy("http://localhost:3000")),
                new BetaPolicy("http://localhost:3000"), new BetaRateLimiter(),
                Clock.fixed(NOW, ZoneOffset.UTC), "test-admin")).build();
        checked.get().uri("/admin/beta/report?from=2026-10-01T00:00:00Z&to=2026-10-18T00:00:00Z")
                .header("X-Parliament-Ingestion-Key", "test-admin").exchange().expectStatus().isBadRequest();
    }

    @Test
    void eventsRequireBetaSessionSameOriginCsrfAndAllowlistedPayload() {
        Map<String, Object> body = Map.of("event", "explainer_opened", "visitKind", "organic");
        client.post().uri("/api/v1/beta/events").bodyValue(body).exchange().expectStatus().isUnauthorized();
        client.post().uri("/api/v1/beta/events").cookie("parliament_beta", TOKEN)
                .header("Origin", "http://localhost:3000").header("X-CSRF-Token", "wrong")
                .bodyValue(body).exchange().expectStatus().isForbidden();
        client.post().uri("/api/v1/beta/events").cookie("parliament_beta", TOKEN)
                .header("Origin", "http://localhost:3000").header("X-CSRF-Token", "csrf")
                .bodyValue(Map.of("event", "explainer_opened", "visitKind", "organic", "url", "political"))
                .exchange().expectStatus().isBadRequest();
        when(repository.record(any(), any(), any())).thenReturn(Mono.empty());
        client.post().uri("/api/v1/beta/events").cookie("parliament_beta", TOKEN)
                .header("Origin", "http://localhost:3000").header("X-CSRF-Token", "csrf")
                .bodyValue(body).exchange().expectStatus().isAccepted();
        verify(repository, times(1)).record(any(), any(), any());
    }

    @Test
    void withdrawalRequiresCsrfAndClearsCookieOnlyAfterSuccessfulDeletion() {
        when(repository.withdraw(any())).thenReturn(Mono.empty());
        client.post().uri("/api/v1/beta/withdraw").cookie("parliament_beta", TOKEN)
                .header("Origin", "http://localhost:3000").header("X-CSRF-Token", "csrf")
                .exchange().expectStatus().isNoContent().expectCookie().maxAge("parliament_beta", java.time.Duration.ZERO);
        verify(repository).withdraw("pseudonym");
    }

    @Test
    void aggregateAcquisitionIsSameOriginAndRejectsExtraFields() {
        when(repository.acquisition(any(), any())).thenReturn(Mono.empty());
        client.post().uri("/api/v1/beta/acquisition").bodyValue(Map.of("source", "instagram"))
                .exchange().expectStatus().isForbidden();
        client.post().uri("/api/v1/beta/acquisition").header("Origin", "http://localhost:3000")
                .bodyValue(Map.of("source", "instagram", "email", "hidden@example.org"))
                .exchange().expectStatus().isBadRequest();
        client.post().uri("/api/v1/beta/acquisition").header("Origin", "http://localhost:3000")
                .bodyValue(Map.of("source", "instagram")).exchange().expectStatus().isAccepted();
        verify(repository, times(1)).acquisition(eq("instagram"), any());
    }

    @Test
    void adminReportNeedsKeyAndDoesNotExposeContacts() {
        String path = "/admin/beta/report?from=2026-10-01T00:00:00Z&to=2026-10-18T00:00:00Z";
        client.get().uri(path).exchange().expectStatus().isForbidden();
        verifyNoInteractions(repository);
        when(repository.report(any(), any(), any())).thenReturn(Mono.just(new BetaReport.Report(
                NOW, "Asia/Seoul", 35, java.util.List.of(), java.util.Map.of())));
        client.get().uri(path).header("X-Parliament-Ingestion-Key", "test-admin")
                .exchange().expectStatus().isOk().expectBody().jsonPath("$.cohorts").isArray()
                .jsonPath("$.contacts").doesNotExist();
    }

    @Test
    void databaseFailureDoesNotReturnSuccessOrIssueCookie() {
        when(repository.enroll(any(), any())).thenReturn(Mono.error(
                new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "beta unavailable")));
        client.post().uri("/api/v1/beta/participants").header("Origin", "http://localhost:3000")
                .bodyValue(Map.of("email", "beta@example.org", "consent", true,
                        "cohort", "external", "source", "direct"))
                .exchange().expectStatus().isEqualTo(503).expectCookie().doesNotExist("parliament_beta");
    }
}
