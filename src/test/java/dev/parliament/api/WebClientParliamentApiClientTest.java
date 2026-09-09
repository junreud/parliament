package dev.parliament.api;

import dev.parliament.config.ParliamentCollectionMode;
import dev.parliament.config.ParliamentIngestionProperties;
import dev.parliament.config.ParliamentMediaType;
import dev.parliament.config.ParliamentSourceDefinition;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import org.springframework.web.reactive.function.client.ClientRequest;
import org.springframework.web.reactive.function.client.ClientResponse;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.core.publisher.Mono;
import reactor.test.StepVerifier;

import java.util.Map;
import java.util.concurrent.atomic.AtomicReference;
import java.util.concurrent.atomic.AtomicInteger;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class WebClientParliamentApiClientTest {

    @Test
    void fetchUsesAllowlistedHttpsHostAndRequiredPagingParameters() {
        AtomicReference<ClientRequest> captured = new AtomicReference<>();
        WebClient webClient = WebClient.builder().exchangeFunction(request -> {
            captured.set(request);
            return Mono.just(ClientResponse.create(HttpStatus.OK)
                    .header("Content-Type", "text/html;charset=UTF-8")
                    .body("""
                            {"ALLSCHEDULE":[
                              {"head":[{"list_total_count":1},{"RESULT":{"CODE":"INFO-000","MESSAGE":"OK"}}]},
                              {"row":[{"CONF_ID":"c1"}]}
                            ]}
                            """)
                    .build());
        }).build();
        ParliamentIngestionProperties properties = properties("test-key");
        ParliamentSourceDefinition source = new ParliamentSourceDefinition(
                "schedule", "ALLSCHEDULE", "일정", "15126132",
                ParliamentMediaType.DATA, ParliamentCollectionMode.PAGE, Map.of("AGE", "22"));
        WebClientParliamentApiClient client = new WebClientParliamentApiClient(
                webClient, properties, new OpenAssemblyResponseParser());

        StepVerifier.create(client.fetch(source, 2, 25))
                .expectNextMatches(page -> page.totalCount() == 1 && page.rows().size() == 1)
                .verifyComplete();

        String query = captured.get().url().getRawQuery();
        assertThat(captured.get().url().getScheme()).isEqualTo("https");
        assertThat(captured.get().url().getHost()).isEqualTo("open.assembly.go.kr");
        assertThat(captured.get().url().getPath()).endsWith("/ALLSCHEDULE");
        assertThat(query).contains("Type=json", "pIndex=2", "pSize=25", "AGE=22", "KEY=test-key");
        assertThat(captured.get().headers().getFirst("User-Agent"))
                .isEqualTo("Mozilla/5.0 (compatible; ParliamentDataPlatform/1.0; +https://github.com/junreud/parliament)");
    }

    @Test
    void rejectsMissingKeyAndNonAssemblyBaseUrlBeforeNetworkCall() {
        WebClient webClient = WebClient.builder()
                .exchangeFunction(request -> Mono.error(new AssertionError("network must not be called")))
                .build();
        ParliamentIngestionProperties missingKey = properties("");
        assertThatThrownBy(() -> new WebClientParliamentApiClient(
                webClient, missingKey, new OpenAssemblyResponseParser()))
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("api-key");

        ParliamentIngestionProperties unsafe = properties("test-key");
        unsafe.setBaseUrl("http://127.0.0.1/internal");
        assertThatThrownBy(() -> new WebClientParliamentApiClient(
                webClient, unsafe, new OpenAssemblyResponseParser()))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("open.assembly.go.kr");
    }

    @Test
    void acceptsLargeJsonPagesWithinTheConfiguredSafetyLimit() {
        String padding = "x".repeat(300_000);
        WebClient webClient = WebClient.builder().exchangeFunction(request -> Mono.just(
                ClientResponse.create(HttpStatus.OK)
                        .header("Content-Type", "text/html;charset=UTF-8")
                        .body("""
                                {"ALLSCHEDULE":[
                                  {"head":[{"list_total_count":1},{"RESULT":{"CODE":"INFO-000","MESSAGE":"OK"}}]},
                                  {"row":[{"CONF_ID":"c1","PAD":"%s"}]}
                                ]}
                                """.formatted(padding))
                        .build()
        )).build();
        WebClientParliamentApiClient client = new WebClientParliamentApiClient(
                webClient, properties("test-key"), new OpenAssemblyResponseParser());
        ParliamentSourceDefinition source = new ParliamentSourceDefinition(
                "schedule", "ALLSCHEDULE", "일정", "15126132",
                ParliamentMediaType.DATA, ParliamentCollectionMode.PAGE, Map.of());

        StepVerifier.create(client.fetch(source, 1, 100))
                .expectNextMatches(page -> page.rows().size() == 1)
                .verifyComplete();
    }

    @Test
    void retriesTransientServerFailuresBeforeReturningThePage() {
        AtomicInteger attempts = new AtomicInteger();
        WebClient webClient = WebClient.builder().exchangeFunction(request -> {
            if (attempts.incrementAndGet() < 3) {
                return Mono.just(ClientResponse.create(HttpStatus.SERVICE_UNAVAILABLE).build());
            }
            return Mono.just(ClientResponse.create(HttpStatus.OK)
                    .body("""
                            {"ALLSCHEDULE":[
                              {"head":[{"list_total_count":0},{"RESULT":{"CODE":"INFO-000","MESSAGE":"OK"}}]}
                            ]}
                            """)
                    .build());
        }).build();
        WebClientParliamentApiClient client = new WebClientParliamentApiClient(
                webClient, properties("test-key"), new OpenAssemblyResponseParser());
        ParliamentSourceDefinition source = new ParliamentSourceDefinition(
                "schedule", "ALLSCHEDULE", "일정", null,
                ParliamentMediaType.DATA, ParliamentCollectionMode.PAGE, Map.of());

        StepVerifier.create(client.fetch(source, 1, 10))
                .expectNextMatches(page -> page.rows().isEmpty())
                .verifyComplete();
        assertThat(attempts).hasValue(3);
    }

    private ParliamentIngestionProperties properties(String apiKey) {
        ParliamentIngestionProperties properties = new ParliamentIngestionProperties();
        properties.setApiKey(apiKey);
        return properties;
    }
}
