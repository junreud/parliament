package dev.parliament.service;

import dev.parliament.api.OpenAssemblyPage;
import dev.parliament.api.ParliamentApiClient;
import dev.parliament.config.ParliamentIngestionProperties;
import dev.parliament.config.ParliamentSourceCatalog;
import dev.parliament.config.ParliamentSourceDefinition;
import dev.parliament.domain.NormalizedParliamentRecord;
import dev.parliament.domain.ParliamentRecordNormalizer;
import dev.parliament.persistence.ParliamentIngestionCheckpoint;
import dev.parliament.persistence.ParliamentStagingRepository;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;

import java.util.List;

public class ParliamentIngestionService {
    private final ParliamentApiClient apiClient;
    private final ParliamentStagingRepository repository;
    private final ParliamentRecordNormalizer normalizer;
    private final ParliamentSourceCatalog catalog;
    private final ParliamentIngestionProperties properties;
    private final ParliamentParameterResolver parameterResolver;

    public ParliamentIngestionService(
            ParliamentApiClient apiClient,
            ParliamentStagingRepository repository,
            ParliamentRecordNormalizer normalizer,
            ParliamentSourceCatalog catalog,
            ParliamentIngestionProperties properties,
            ParliamentParameterResolver parameterResolver
    ) {
        this.apiClient = apiClient;
        this.repository = repository;
        this.normalizer = normalizer;
        this.catalog = catalog;
        this.properties = properties;
        this.parameterResolver = parameterResolver;
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
        return Flux.fromIterable(resolveSources(request))
                .concatMap(source -> parameterResolver.resolveSample(source)
                        .flatMap(resolved -> repository.checkpoint(source.key())
                                .defaultIfEmpty(ParliamentIngestionCheckpoint.initial())
                                .flatMap(checkpoint -> checkpoint.complete()
                                        ? Mono.just(alreadyComplete(source))
                                        : ingestPage(resolved, checkpoint.nextPage(), request, 0)))
                        .onErrorResume(error -> Mono.just(failed(source, error))))
                .collectList()
                .map(reports -> new ParliamentIngestionReport(true, reports));
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

    private int peopleCount(List<NormalizedParliamentRecord> records) {
        return records.stream().mapToInt(record -> record.people().size()).sum();
    }

    private boolean isComplete(OpenAssemblyPage page, int pageNumber, int pageSize) {
        return page.rows().size() < pageSize
                || page.totalCount() > 0 && (long) pageNumber * pageSize >= page.totalCount();
    }

    private List<ParliamentSourceDefinition> resolveSources(ParliamentIngestionRequest request) {
        if (request.sourceKeys().isEmpty()) {
            return catalog.active();
        }
        return request.sourceKeys().stream().map(catalog::requireActive).toList();
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
}
