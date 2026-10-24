package dev.parliament.tracking;

import static org.mockito.Mockito.*;

import org.junit.jupiter.api.Test;
import org.springframework.test.web.reactive.server.WebTestClient;

import reactor.core.publisher.Mono;

import java.util.List;

class TrackingControllerTest {
    @Test
    void publicFeedValidatesCursorAndReturnsOnlyRepositoryPublishedResults() {
        TrackingRepository repository = mock(TrackingRepository.class);
        when(repository.feed(null, null, null, null, null, null, 20))
                .thenReturn(Mono.just(new TrackingRepository.Page(List.of(), null)));
        TrackingDirectory directory = mock(TrackingDirectory.class);
        WebTestClient client =
                WebTestClient.bindToController(
                                new TrackingController(repository, directory, new TrackingIssues()))
                        .build();
        client.get()
                .uri("/api/v1/activities")
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody()
                .jsonPath("$.items")
                .isEmpty();
        client.get()
                .uri("/api/v1/activities?cursor=invalid")
                .exchange()
                .expectStatus()
                .isBadRequest();
        client.get().uri("/api/v1/activities?limit=1000").exchange().expectStatus().isBadRequest();
        verify(repository, times(1)).feed(null, null, null, null, null, null, 20);
    }

    @Test
    void administrativeImportRejectsUnauthorizedBeforeDatabaseAccess() {
        TrackingRepository repository = mock(TrackingRepository.class);
        TrackingProjection projection = mock(TrackingProjection.class);
        WebTestClient client =
                WebTestClient.bindToController(
                                new TrackingAdminController(
                                        repository,
                                        projection,
                                        new TrackingAdminAuthorization("test-secret")))
                        .build();
        client.post()
                .uri("/admin/tracking/events")
                .header("X-Parliament-Ingestion-Key", "wrong")
                .bodyValue(
                        TrackingPolicyTest.activity(
                                "https://open.assembly.go.kr/x", "BILL_ID=b1", "unknown"))
                .exchange()
                .expectStatus()
                .isForbidden();
        verifyNoInteractions(repository);
    }
}
