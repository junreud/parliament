package dev.parliament.service;

import dev.parliament.api.OpenAssemblyPage;
import dev.parliament.api.ParliamentApiClient;
import dev.parliament.config.ParliamentCollectionMode;
import dev.parliament.config.ParliamentIngestionProperties;
import dev.parliament.config.ParliamentMediaType;
import dev.parliament.config.ParliamentSourceCatalog;
import dev.parliament.config.ParliamentSourceDefinition;
import dev.parliament.domain.NormalizedParliamentRecord;
import dev.parliament.domain.ParliamentRecordNormalizer;
import dev.parliament.persistence.ParliamentIngestionCheckpoint;
import dev.parliament.persistence.ParliamentStagingRepository;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import reactor.core.publisher.Mono;
import reactor.test.StepVerifier;

import java.util.List;
import java.util.Map;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyBoolean;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.assertj.core.api.Assertions.assertThat;

@ExtendWith(MockitoExtension.class)
class ParliamentIngestionServiceTest {

    @Mock private ParliamentApiClient apiClient;
    @Mock private ParliamentStagingRepository repository;
    @Mock private ParliamentRecordNormalizer normalizer;

    private ParliamentSourceDefinition source;
    private ParliamentIngestionProperties properties;

    @BeforeEach
    void setUp() {
        source = new ParliamentSourceDefinition(
                "assembly-members", "ALLNAMEMBER", "국회의원 정보 통합 API", "15126133",
                ParliamentMediaType.DATA, ParliamentCollectionMode.PAGE, Map.of("AGE", "22"));
        properties = new ParliamentIngestionProperties();
    }

    @Test
    void preflightFetchesAndNormalisesOnePageWithoutWriting() {
        ParliamentSourceCatalog catalog = ParliamentSourceCatalog.of(List.of(source));
        when(apiClient.fetch(source, 1, 5)).thenReturn(Mono.just(new OpenAssemblyPage(
                1, List.of(Map.of("NAAS_CD", "m1", "NAAS_NM", "홍길동")))));
        when(normalizer.normalize(source, Map.of("NAAS_CD", "m1", "NAAS_NM", "홍길동")))
                .thenReturn(new NormalizedParliamentRecord("m1", "hash", "{}", List.of()));
        ParliamentIngestionService service = service(catalog);

        StepVerifier.create(service.preflight(new ParliamentIngestionRequest(List.of(source.key()), 5, 1, false)))
                .expectNextMatches(report -> report.sources().size() == 1
                        && report.sources().get(0).records() == 1
                        && report.writePerformed() == false)
                .verifyComplete();

        verify(repository, never()).savePage(any(), any(), anyInt(), anyInt(), anyBoolean());
        verify(repository, never()).checkpoint(any());
    }

    @Test
    void executeRequiresServerWriteFlagAndRequestConfirmation() {
        ParliamentSourceCatalog catalog = ParliamentSourceCatalog.of(List.of(source));
        ParliamentIngestionService service = service(catalog);

        StepVerifier.create(service.run(new ParliamentIngestionRequest(List.of(source.key()), 10, 1, true)))
                .expectErrorMatches(error -> error instanceof IllegalStateException
                        && error.getMessage().contains("write-enabled"))
                .verify();

        properties.setWriteEnabled(true);
        StepVerifier.create(service.run(new ParliamentIngestionRequest(List.of(source.key()), 10, 1, false)))
                .expectErrorMatches(error -> error instanceof IllegalArgumentException
                        && error.getMessage().contains("confirmWrite"))
                .verify();

        verify(apiClient, never()).fetch(any(), anyInt(), anyInt());
        verify(repository, never()).savePage(any(), any(), anyInt(), anyInt(), anyBoolean());
    }

    @Test
    void preflightReportsSourceFailureWithoutWritingOrFailingWholeReport() {
        ParliamentSourceCatalog catalog = ParliamentSourceCatalog.of(List.of(source));
        when(apiClient.fetch(source, 1, 5)).thenReturn(Mono.error(
                new dev.parliament.api.OpenAssemblyApiException("Open Assembly API error ERROR-290")));

        StepVerifier.create(service(catalog).preflight(
                        new ParliamentIngestionRequest(List.of(source.key()), 5, 1, false)))
                .assertNext(report -> {
                    assertThat(report.writePerformed()).isFalse();
                    assertThat(report.sources()).singleElement().satisfies(failed -> {
                        assertThat(failed.status()).isEqualTo(ParliamentSourceStatus.FAILED);
                        assertThat(failed.message()).contains("ERROR-290");
                    });
                })
                .verifyComplete();
        verify(repository, never()).savePage(any(), any(), anyInt(), anyInt(), anyBoolean());
    }

    @Test
    void runPersistsOnePageAndReportsPartialWhenPageLimitIsReached() {
        ParliamentSourceCatalog catalog = ParliamentSourceCatalog.of(List.of(source));
        Map<String, Object> row = Map.of("NAAS_CD", "m1", "NAAS_NM", "홍길동");
        NormalizedParliamentRecord normalized = new NormalizedParliamentRecord(
                "m1", "hash", "{}", List.of());
        properties.setWriteEnabled(true);
        when(repository.checkpoint(source.key())).thenReturn(Mono.just(
                new ParliamentIngestionCheckpoint(1, false)));
        when(apiClient.fetch(source, 1, 1)).thenReturn(Mono.just(new OpenAssemblyPage(10, List.of(row))));
        when(normalizer.normalize(source, row)).thenReturn(normalized);
        when(repository.savePage(source, List.of(normalized), 1, 2, false)).thenReturn(Mono.empty());

        StepVerifier.create(service(catalog).run(
                        new ParliamentIngestionRequest(List.of(source.key()), 1, 1, true)))
                .assertNext(report -> {
                    assertThat(report.writePerformed()).isTrue();
                    assertThat(report.sources()).singleElement().satisfies(partial -> {
                        assertThat(partial.status()).isEqualTo(ParliamentSourceStatus.PARTIAL);
                        assertThat(partial.complete()).isFalse();
                    });
                })
                .verifyComplete();

        verify(repository).savePage(source, List.of(normalized), 1, 2, false);
    }

    @Test
    void completedCheckpointSkipsExternalApiAndDatabaseWrites() {
        ParliamentSourceCatalog catalog = ParliamentSourceCatalog.of(List.of(source));
        properties.setWriteEnabled(true);
        when(repository.checkpoint(source.key())).thenReturn(Mono.just(
                new ParliamentIngestionCheckpoint(5, true)));

        StepVerifier.create(service(catalog).run(
                        new ParliamentIngestionRequest(List.of(source.key()), 10, 1, true)))
                .assertNext(report -> assertThat(report.sources()).singleElement()
                        .satisfies(done -> assertThat(done.status()).isEqualTo(ParliamentSourceStatus.COMPLETE)))
                .verifyComplete();

        verify(apiClient, never()).fetch(any(), anyInt(), anyInt());
        verify(repository, never()).savePage(any(), any(), anyInt(), anyInt(), anyBoolean());
    }

    private ParliamentIngestionService service(ParliamentSourceCatalog catalog) {
        return new ParliamentIngestionService(apiClient, repository, normalizer, catalog, properties);
    }
}
