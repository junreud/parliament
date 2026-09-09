package dev.parliament.persistence;

import dev.parliament.service.IngestionRunStatus;
import dev.parliament.service.IngestionTrigger;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;

import java.time.Instant;
import java.util.List;

public interface ParliamentIngestionHistoryRepository {
    Mono<Long> startRun(
            IngestionTrigger trigger,
            Instant scheduledFor,
            Instant startedAt,
            List<IngestionSourceSchedule> sources
    );

    Mono<Void> markSourceRunStarted(long runId, String sourceKey, Instant startedAt);

    Mono<Void> completeSourceRun(
            long runId,
            String sourceKey,
            IngestionSourceCompletion completion
    );

    Mono<Void> completeRun(
            long runId,
            IngestionRunStatus status,
            Instant finishedAt,
            int succeededSources,
            int failedSources
    );

    Flux<IngestionHistoryEntry> findHistory(Instant fromInclusive, Instant toExclusive);
}
