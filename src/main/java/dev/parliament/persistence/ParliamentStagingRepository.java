package dev.parliament.persistence;

import dev.parliament.config.ParliamentSourceDefinition;
import dev.parliament.domain.NormalizedParliamentRecord;
import reactor.core.publisher.Mono;

import java.util.List;
import java.time.Instant;

public interface ParliamentStagingRepository
        extends ParliamentParameterValueRepository, ParliamentSocialVerificationRepository {
    Mono<ParliamentIngestionCheckpoint> checkpoint(String sourceKey, String variantKey);

    Mono<Void> resetCheckpoint(String sourceKey, String variantKey);

    Mono<Void> savePage(
            ParliamentSourceDefinition source,
            List<NormalizedParliamentRecord> records,
            int currentPage,
            int nextPage,
            boolean complete
    );

    Mono<ParliamentPageWriteResult> saveChangedPage(
            ParliamentSourceDefinition source,
            List<NormalizedParliamentRecord> records,
            int currentPage,
            int nextPage,
            boolean complete
    );

    Mono<Integer> finalizeSourceSnapshot(String sourceKey, Instant observedSince);

    Mono<Instant> lastSuccessfulSyncAt(String sourceKey);

    Mono<Void> markSourceSyncStarted(String sourceKey, Instant startedAt);

    Mono<Void> markSourceSyncCompleted(String sourceKey, Instant watermark, Instant finishedAt);

    Mono<Void> markSourceSyncFailed(String sourceKey, Instant finishedAt, String errorCode);
}
