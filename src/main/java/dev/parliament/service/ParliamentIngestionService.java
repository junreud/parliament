package dev.parliament.service;

import dev.parliament.api.OpenAssemblyPage;
import dev.parliament.api.ParliamentApiClient;
import dev.parliament.config.ParliamentIngestionProperties;
import dev.parliament.config.ParliamentSourceCatalog;
import dev.parliament.config.ParliamentSourceDefinition;
import dev.parliament.domain.NormalizedParliamentRecord;
import dev.parliament.domain.ParliamentRecordNormalizer;
import dev.parliament.persistence.ParliamentIngestionCheckpoint;
import dev.parliament.persistence.IngestionSourceCompletion;
import dev.parliament.persistence.IngestionSourceSchedule;
import dev.parliament.persistence.ParliamentStagingRepository;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;
import reactor.core.Exceptions;

import java.util.List;
import java.util.Objects;
import java.time.Clock;
import java.time.Instant;
import dev.parliament.persistence.ParliamentPageWriteResult;
import java.util.Comparator;
import java.util.Set;
import java.util.Optional;

public class ParliamentIngestionService {
    private static final Set<String> AUTHORITATIVE_SNAPSHOT_SOURCES = Set.of(
            "nwvrqwxyaytdsfvhu", "negnlnyvatsjwocar");
    private final ParliamentApiClient apiClient;
    private final ParliamentStagingRepository repository;
    private final ParliamentRecordNormalizer normalizer;
    private final ParliamentSourceCatalog catalog;
    private final ParliamentIngestionProperties properties;
    private final ParliamentParameterResolver parameterResolver;
    private final Clock clock;

    public ParliamentIngestionService(
            ParliamentApiClient apiClient,
            ParliamentStagingRepository repository,
            ParliamentRecordNormalizer normalizer,
            ParliamentSourceCatalog catalog,
            ParliamentIngestionProperties properties,
            ParliamentParameterResolver parameterResolver,
            Clock clock
    ) {
        this.apiClient = apiClient;
        this.repository = repository;
        this.normalizer = normalizer;
        this.catalog = catalog;
        this.properties = properties;
        this.parameterResolver = parameterResolver;
        this.clock = clock;
    }

    public Mono<ParliamentIngestionReport> preflight(ParliamentIngestionRequest request) {
        validate(request);
        return Flux.fromIterable(resolveSources(request))
                .concatMap(source -> parameterResolver.resolveSample(source)
                        .flatMap(resolved -> apiClient.fetch(resolved, 1, request.pageSize())
                                .map(page -> report(source, normalize(source, page), 1,
                                        isComplete(page, 1, request.pageSize()), ParliamentSourceStatus.READY)))
                        .onErrorResume(error -> Mono.just(failed(source, error))))
                .collectList()
                .map(reports -> new ParliamentIngestionReport(false, reports));
    }

    public Mono<ParliamentIngestionReport> run(ParliamentIngestionRequest request) {
        validate(request);
        if (!properties.isWriteEnabled()) {
            return Mono.error(new IllegalStateException("parliament ingestion write-enabled is false"));
        }
        if (!request.confirmWrite()) {
            return Mono.error(new IllegalArgumentException("confirmWrite must be true"));
        }
        Instant startedAt = clock.instant();
        List<ParliamentSourceDefinition> sources = resolveSources(request);
        List<IngestionSourceSchedule> schedules = schedules(sources);
        return repository.startRun(IngestionTrigger.MANUAL, null, startedAt, schedules)
                .flatMap(runId -> Flux.fromIterable(sources)
                        .concatMap(source -> repository.markSourceRunStarted(
                                        runId, source.key(), clock.instant())
                                .then(parameterResolver.resolveAll(source)
                                        .concatMap(resolved -> repository.checkpoint(
                                                        source.key(), resolved.variantKey())
                                                .defaultIfEmpty(ParliamentIngestionCheckpoint.initial())
                                                .flatMap(checkpoint -> checkpoint.complete()
                                                        ? Mono.just(alreadyComplete(resolved))
                                                        : ingestPage(resolved, checkpoint.nextPage(), request, 0)))
                                        .collectList()
                                        .map(reports -> aggregate(source, reports))
                                        .onErrorResume(error -> Mono.just(failed(source, error))))
                                .flatMap(report -> repository.completeSourceRun(
                                                runId, source.key(), completion(report))
                                        .thenReturn(report)))
                        .collectList()
                        .flatMap(reports -> completeInitialRun(runId, reports)
                                .thenReturn(new ParliamentIngestionReport(true, reports)))
                        .onErrorResume(error -> repository.completeRun(
                                        runId, IngestionRunStatus.FAILED,
                                        clock.instant(), 0, sources.size())
                                .onErrorResume(ignored -> Mono.empty())
                                .then(Mono.error(error))));
    }

    public Mono<ParliamentSyncReport> synchronize(ParliamentIngestionRequest request) {
        return synchronize(request, IngestionTrigger.MANUAL, null);
    }

    public Mono<ParliamentSyncReport> synchronizeAutomatically(ParliamentIngestionRequest request) {
        return synchronize(request, IngestionTrigger.AUTOMATIC, clock.instant());
    }

    private Mono<ParliamentSyncReport> synchronize(
            ParliamentIngestionRequest request,
            IngestionTrigger trigger,
            Instant scheduledFor
    ) {
        validateWriteRequest(request);
        Instant startedAt = clock.instant();
        List<ParliamentSourceDefinition> sources = resolveSources(request);
        List<IngestionSourceSchedule> schedules = schedules(sources);
        return repository.startRun(trigger, scheduledFor, startedAt, schedules)
                .flatMap(runId -> Flux.fromIterable(sources)
                        .concatMap(source -> repository.markSourceRunStarted(
                                        runId, source.key(), clock.instant())
                                .then(synchronizeSource(source, request))
                                .flatMap(report -> repository.completeSourceRun(
                                                runId, source.key(), completion(report))
                                        .thenReturn(report)))
                        .collectList()
                        .flatMap(reports -> {
                            int succeeded = (int) reports.stream()
                                    .map(IngestionSourceOutcome::from)
                                    .filter(IngestionSourceOutcome::isSuccess)
                                    .count();
                            int failed = reports.size() - succeeded;
                            IngestionRunStatus status = failed == 0
                                    ? IngestionRunStatus.SUCCESS
                                    : succeeded == 0 ? IngestionRunStatus.FAILED
                                    : IngestionRunStatus.PARTIAL;
                            Instant finishedAt = clock.instant();
                            return repository.completeRun(
                                            runId, status, finishedAt, succeeded, failed)
                                    .thenReturn(new ParliamentSyncReport(
                                            startedAt, finishedAt, reports));
                        })
                        .onErrorResume(error -> repository.completeRun(
                                        runId, IngestionRunStatus.FAILED,
                                        clock.instant(), 0, sources.size())
                                .onErrorResume(ignored -> Mono.empty())
                                .then(Mono.error(error))));
    }

    private List<IngestionSourceSchedule> schedules(List<ParliamentSourceDefinition> sources) {
        return sources.stream()
                .map(source -> new IngestionSourceSchedule(
                        source.key(), source.apiCode(), source.name(),
                        parameterResolver.expectation(source)))
                .toList();
    }

    private Mono<Void> completeInitialRun(long runId, List<ParliamentSourceReport> reports) {
        int succeeded = (int) reports.stream()
                .filter(report -> report.status() == ParliamentSourceStatus.COMPLETE)
                .count();
        int failed = reports.size() - succeeded;
        IngestionRunStatus status = failed == 0
                ? IngestionRunStatus.SUCCESS
                : succeeded == 0 ? IngestionRunStatus.FAILED : IngestionRunStatus.PARTIAL;
        return repository.completeRun(runId, status, clock.instant(), succeeded, failed);
    }

    private IngestionSourceCompletion completion(ParliamentSyncSourceReport report) {
        IngestionSourceOutcome outcome = IngestionSourceOutcome.from(report);
        String errorCode = outcome == IngestionSourceOutcome.RETRY_EXHAUSTED
                ? "RETRY_EXHAUSTED"
                : outcome == IngestionSourceOutcome.FAILED ? "SOURCE_FAILED"
                : outcome == IngestionSourceOutcome.PARTIAL ? "INCOMPLETE" : null;
        return new IngestionSourceCompletion(
                outcome, clock.instant(), report.variants(), report.scanned(),
                report.changed(), report.unchanged(), report.removed(), report.pages(),
                errorCode, report.message());
    }

    private IngestionSourceCompletion completion(ParliamentSourceReport report) {
        IngestionSourceOutcome outcome;
        if (report.status() == ParliamentSourceStatus.FAILED) {
            outcome = IngestionSourceOutcome.FAILED;
        } else if (report.status() == ParliamentSourceStatus.PARTIAL || !report.complete()) {
            outcome = IngestionSourceOutcome.PARTIAL;
        } else if (report.records() == 0) {
            outcome = "already complete".equals(report.message())
                    ? IngestionSourceOutcome.SUCCESS_UNCHANGED
                    : IngestionSourceOutcome.SUCCESS_EMPTY;
        } else {
            outcome = IngestionSourceOutcome.SUCCESS_CHANGED;
        }
        String errorCode = outcome == IngestionSourceOutcome.FAILED
                ? "SOURCE_FAILED" : outcome == IngestionSourceOutcome.PARTIAL ? "INCOMPLETE" : null;
        return new IngestionSourceCompletion(
                outcome, clock.instant(), 1, report.records(), report.records(),
                0, 0, report.pages(), errorCode, report.message());
    }

    private Mono<ParliamentSyncSourceReport> synchronizeSource(
            ParliamentSourceDefinition source,
            ParliamentIngestionRequest request
    ) {
        Instant observedSince = clock.instant();
        return repository.lastSuccessfulSyncAt(source.key())
                .map(Optional::of)
                .defaultIfEmpty(Optional.empty())
                .flatMap(previous -> repository.markSourceSyncStarted(source.key(), observedSince)
                        .thenMany(previous
                                .map(watermark -> parameterResolver.resolveChanged(source, watermark))
                                .orElseGet(() -> parameterResolver.resolveAll(source)))
                        .concatMap(resolved -> repository.resetCheckpoint(source.key(), resolved.variantKey())
                                .then(synchronizePage(resolved, 1, request, 0))
                                .onErrorResume(error -> Mono.just(VariantSyncReport.failed(error))))
                        .collectList()
                        .map(variants -> aggregateSync(
                                source, variants,
                                previous.isPresent() && parameterResolver.dependsOnSourceRecords(source))))
                .flatMap(report -> report.complete()
                                && AUTHORITATIVE_SNAPSHOT_SOURCES.contains(source.key())
                        ? repository.finalizeSourceSnapshot(source.key(), observedSince)
                                .map(removed -> new ParliamentSyncSourceReport(
                                        report.sourceKey(), report.variants(), report.scanned(),
                                        report.changed(), report.unchanged(), removed, report.pages(),
                                        report.complete(), report.status(), report.message(),
                                        report.retryExhausted()))
                        : Mono.just(report))
                .flatMap(report -> report.complete()
                        ? repository.markSourceSyncCompleted(
                                        source.key(), observedSince, clock.instant())
                                .thenReturn(report)
                        : repository.markSourceSyncFailed(
                                        source.key(), clock.instant(), "INCOMPLETE")
                                .thenReturn(report))
                .onErrorResume(error -> repository.markSourceSyncFailed(
                                source.key(), clock.instant(), error.getClass().getSimpleName())
                        .onErrorResume(ignored -> Mono.empty())
                        .thenReturn(new ParliamentSyncSourceReport(
                                source.key(), 0, 0, 0, 0, 0, 0, false,
                                ParliamentSourceStatus.FAILED, safeError(error),
                                Exceptions.isRetryExhausted(error))));
    }

    private Mono<VariantSyncReport> synchronizePage(
            ParliamentSourceDefinition source,
            int pageNumber,
            ParliamentIngestionRequest request,
            int completedPages
    ) {
        return Mono.defer(() -> apiClient.fetch(source, pageNumber, request.pageSize())
                .flatMap(page -> {
                    List<NormalizedParliamentRecord> records = normalize(source, page);
                    boolean complete = isComplete(page, pageNumber, request.pageSize());
                    int nextPage = complete ? pageNumber : pageNumber + 1;
                    return repository.saveChangedPage(source, records, pageNumber, nextPage, complete)
                            .flatMap(write -> {
                                int pages = completedPages + 1;
                                VariantSyncReport current = VariantSyncReport.of(write, 1, complete);
                                if (!complete && pages < request.maxPages()) {
                                    return synchronizePage(source, nextPage, request, pages)
                                            .map(current::plus);
                                }
                                return Mono.just(current);
                            });
                }));
    }

    private ParliamentSyncSourceReport aggregateSync(
            ParliamentSourceDefinition source,
            List<VariantSyncReport> variants,
            boolean emptyMeansNoChanges
    ) {
        if (variants.isEmpty()) {
            return new ParliamentSyncSourceReport(
                    source.key(), 0, 0, 0, 0, 0, 0, emptyMeansNoChanges,
                    emptyMeansNoChanges ? ParliamentSourceStatus.COMPLETE : ParliamentSourceStatus.FAILED,
                    emptyMeansNoChanges ? "no changed parent identifiers" : "no parameter variants resolved",
                    false);
        }
        boolean failed = variants.stream().anyMatch(item -> item.status() == ParliamentSourceStatus.FAILED);
        boolean complete = !failed && variants.stream().allMatch(VariantSyncReport::complete);
        boolean retryExhausted = variants.stream().anyMatch(VariantSyncReport::retryExhausted);
        String message = variants.stream().map(VariantSyncReport::message)
                .filter(Objects::nonNull).distinct().reduce((left, right) -> left + "; " + right)
                .orElse(null);
        return new ParliamentSyncSourceReport(
                source.key(), variants.size(),
                variants.stream().mapToInt(VariantSyncReport::scanned).sum(),
                variants.stream().mapToInt(VariantSyncReport::changed).sum(),
                variants.stream().mapToInt(VariantSyncReport::unchanged).sum(),
                0,
                variants.stream().mapToInt(VariantSyncReport::pages).sum(),
                complete,
                failed ? ParliamentSourceStatus.FAILED
                        : complete ? ParliamentSourceStatus.COMPLETE : ParliamentSourceStatus.PARTIAL,
                message,
                retryExhausted);
    }

    private Mono<ParliamentSourceReport> ingestPage(
            ParliamentSourceDefinition source,
            int pageNumber,
            ParliamentIngestionRequest request,
            int completedPages
    ) {
        return Mono.defer(() -> apiClient.fetch(source, pageNumber, request.pageSize())
                .flatMap(page -> {
                    List<NormalizedParliamentRecord> records = normalize(source, page);
                    boolean complete = isComplete(page, pageNumber, request.pageSize());
                    int nextPage = complete ? pageNumber : pageNumber + 1;
                    return repository.savePage(source, records, pageNumber, nextPage, complete)
                            .then(Mono.defer(() -> {
                                int pages = completedPages + 1;
                                if (!complete && pages < request.maxPages()) {
                                    return ingestPage(source, nextPage, request, pages)
                                            .map(next -> new ParliamentSourceReport(
                                                    source.key(),
                                                    source.apiCode(),
                                                    records.size() + next.records(),
                                                    peopleCount(records) + next.people(),
                                                    next.pages(),
                                                    next.complete(),
                                                    next.status(),
                                                    next.message()));
                                }
                                return Mono.just(report(source, records, pages, complete,
                                        ParliamentSourceStatus.PARTIAL));
                            }));
                }));
    }

    private List<NormalizedParliamentRecord> normalize(
            ParliamentSourceDefinition source,
            OpenAssemblyPage page
    ) {
        return page.rows().stream().map(row -> normalizer.normalize(source, row)).toList();
    }

    private ParliamentSourceReport report(
            ParliamentSourceDefinition source,
            List<NormalizedParliamentRecord> records,
            int pages,
            boolean complete,
            ParliamentSourceStatus incompleteStatus
    ) {
        return new ParliamentSourceReport(
                source.key(),
                source.apiCode(),
                records.size(),
                peopleCount(records),
                pages,
                complete,
                complete ? ParliamentSourceStatus.COMPLETE : incompleteStatus,
                null
        );
    }

    private ParliamentSourceReport failed(ParliamentSourceDefinition source, Throwable error) {
        return ParliamentSourceReport.failed(source.key(), source.apiCode(), error);
    }

    private ParliamentSourceReport alreadyComplete(ParliamentSourceDefinition source) {
        return new ParliamentSourceReport(source.key(), source.apiCode(), 0, 0, 0,
                true, ParliamentSourceStatus.COMPLETE, "already complete");
    }

    private ParliamentSourceReport aggregate(
            ParliamentSourceDefinition source,
            List<ParliamentSourceReport> variants
    ) {
        if (variants.isEmpty()) {
            return failed(source, new IllegalStateException("no parameter variants resolved"));
        }
        int records = variants.stream().mapToInt(ParliamentSourceReport::records).sum();
        int people = variants.stream().mapToInt(ParliamentSourceReport::people).sum();
        int pages = variants.stream().mapToInt(ParliamentSourceReport::pages).sum();
        boolean complete = variants.stream().allMatch(ParliamentSourceReport::complete);
        ParliamentSourceStatus status = variants.stream()
                .map(ParliamentSourceReport::status)
                .filter(candidate -> candidate == ParliamentSourceStatus.FAILED)
                .findFirst()
                .orElseGet(() -> complete ? ParliamentSourceStatus.COMPLETE : ParliamentSourceStatus.PARTIAL);
        String message = variants.stream().map(ParliamentSourceReport::message)
                .filter(Objects::nonNull).distinct().reduce((left, right) -> left + "; " + right)
                .orElse(null);
        return new ParliamentSourceReport(
                source.key(), source.apiCode(), records, people, pages, complete, status, message);
    }

    private int peopleCount(List<NormalizedParliamentRecord> records) {
        return records.stream().mapToInt(record -> record.people().size()).sum();
    }

    private boolean isComplete(OpenAssemblyPage page, int pageNumber, int pageSize) {
        return page.rows().size() < pageSize
                || page.totalCount() > 0 && (long) pageNumber * pageSize >= page.totalCount();
    }

    private List<ParliamentSourceDefinition> resolveSources(ParliamentIngestionRequest request) {
        List<ParliamentSourceDefinition> selected = request.sourceKeys().isEmpty()
                ? catalog.active()
                : request.sourceKeys().stream().map(catalog::requireActive).toList();
        return selected.stream()
                .sorted(Comparator.comparing(parameterResolver::dependsOnSourceRecords))
                .toList();
    }

    private void validate(ParliamentIngestionRequest request) {
        if (request == null) {
            throw new IllegalArgumentException("request is required");
        }
        if (request.pageSize() < 1 || request.pageSize() > properties.getMaxPageSize()) {
            throw new IllegalArgumentException("pageSize must be between 1 and " + properties.getMaxPageSize());
        }
        if (request.maxPages() < 1 || request.maxPages() > properties.getMaxPagesPerRun()) {
            throw new IllegalArgumentException("maxPages must be between 1 and " + properties.getMaxPagesPerRun());
        }
    }

    private void validateWriteRequest(ParliamentIngestionRequest request) {
        validate(request);
        if (!properties.isWriteEnabled()) {
            throw new IllegalStateException("parliament ingestion write-enabled is false");
        }
        if (!request.confirmWrite()) {
            throw new IllegalArgumentException("confirmWrite must be true");
        }
    }

    private String safeError(Throwable error) {
        return error instanceof dev.parliament.api.OpenAssemblyApiException
                ? error.getMessage()
                : "source sync failed: " + error.getClass().getSimpleName();
    }

    private record VariantSyncReport(
            int scanned,
            int changed,
            int unchanged,
            int pages,
            boolean complete,
            ParliamentSourceStatus status,
            String message,
            boolean retryExhausted
    ) {
        static VariantSyncReport of(ParliamentPageWriteResult write, int pages, boolean complete) {
            return new VariantSyncReport(
                    write.received(), write.changed(), write.unchanged(), pages, complete,
                    complete ? ParliamentSourceStatus.COMPLETE : ParliamentSourceStatus.PARTIAL,
                    null, false);
        }

        static VariantSyncReport failed(Throwable error) {
            return new VariantSyncReport(
                    0, 0, 0, 0, false, ParliamentSourceStatus.FAILED,
                    "variant sync failed: " + error.getClass().getSimpleName(),
                    Exceptions.isRetryExhausted(error));
        }

        VariantSyncReport plus(VariantSyncReport next) {
            return new VariantSyncReport(
                    scanned + next.scanned,
                    changed + next.changed,
                    unchanged + next.unchanged,
                    pages + next.pages,
                    next.complete,
                    next.status,
                    next.message,
                    retryExhausted || next.retryExhausted);
        }
    }
}
