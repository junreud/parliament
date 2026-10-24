package dev.parliament.tracking;

import static org.mockito.Mockito.*;

import org.junit.jupiter.api.Test;
import org.springframework.test.web.reactive.server.WebTestClient;

import reactor.core.publisher.Mono;

import java.util.List;

class TrackingAuthControllerTest {
    @Test
    void unauthenticatedMeIsGenericAndMutationsRequireSessionAndOrigin() {
        var repository = mock(TrackingAuthRepository.class);
        when(repository.me(null))
                .thenReturn(
                        Mono.just(new TrackingAuthRepository.Me(false, null, List.of(), "off")));
        when(repository.current(null)).thenReturn(Mono.empty());
        var client =
                WebTestClient.bindToController(
                                new TrackingAuthController(
                                        repository,
                                        new TrackingAuthPolicy("http://localhost:3000")))
                        .build();
        client.get()
                .uri("/api/v1/me")
                .exchange()
                .expectStatus()
                .isOk()
                .expectBody()
                .jsonPath("$.authenticated")
                .isEqualTo(false);
        client.put()
                .uri("/api/v1/me/follows")
                .header("Origin", "http://localhost:3000")
                .bodyValue(java.util.Map.of("follows", List.of(), "frequency", "off"))
                .exchange()
                .expectStatus()
                .isUnauthorized();
        client.post()
                .uri("/api/v1/auth/request-link")
                .header("Origin", "https://evil.test")
                .bodyValue(java.util.Map.of("email", "user@example.test"))
                .exchange()
                .expectStatus()
                .isForbidden();
        verify(repository, never()).requestLink(anyString(), anyString());
    }
}
