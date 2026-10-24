package dev.parliament.service;

import dev.parliament.config.ParliamentIngestionProperties;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.time.Duration;
import java.util.List;

@Component
@ConditionalOnProperty(
        prefix = "parliament.ingestion", name = "automatic-enabled", havingValue = "true")
public class ParliamentAutomaticSyncScheduler {
    private static final Logger LOG = LoggerFactory.getLogger(ParliamentAutomaticSyncScheduler.class);
    private final ParliamentIngestionService ingestionService;
    private final ParliamentSocialVerificationService socialVerificationService;
    private final ParliamentIngestionProperties properties;
    private final ParliamentJobGuard jobGuard;

    public ParliamentAutomaticSyncScheduler(
            ParliamentIngestionService ingestionService,
            ParliamentSocialVerificationService socialVerificationService,
            ParliamentIngestionProperties properties,
            ParliamentJobGuard jobGuard
    ) {
        this.ingestionService = ingestionService;
        this.socialVerificationService = socialVerificationService;
        this.properties = properties;
        this.jobGuard = jobGuard;
    }

    @Scheduled(
            cron = "${parliament.ingestion.incremental-cron:0 0 4 * * *}",
            zone = "${parliament.ingestion.incremental-zone:Asia/Seoul}")
    public void synchronize() {
        run(properties.getIncrementalSourceKeys(), false);
    }

    @Scheduled(cron = "${parliament.ingestion.daily-cron:0 0 4 * * *}",
            zone = "${parliament.ingestion.incremental-zone:Asia/Seoul}")
    public void synchronizeDaily() {
        run(properties.getDailySourceKeys(), false);
    }

    @Scheduled(cron = "${parliament.ingestion.reconciliation-cron:0 0 3 * * SUN}",
            zone = "${parliament.ingestion.incremental-zone:Asia/Seoul}")
    public void reconcileWeekly() {
        if (properties.isReconciliationEnabled()) {
            run(java.util.stream.Stream.concat(properties.getIncrementalSourceKeys().stream(),
                    properties.getDailySourceKeys().stream()).distinct().toList(), true);
        }
    }

    private void run(List<String> sources, boolean reconciliation) {
        if (sources.isEmpty()) {
            LOG.warn("automatic sync skipped: explicitly verified source keys are required");
            return;
        }
        if (!jobGuard.tryAcquire()) {
            return;
        }
        ParliamentIngestionRequest request = new ParliamentIngestionRequest(
                sources, properties.getIncrementalPageSize(),
                properties.getIncrementalMaxPages(), true);
        (reconciliation ? ingestionService.reconcileAutomatically(request)
                : ingestionService.synchronizeAutomatically(request))
                .flatMap(ignored -> properties.isSocialVerificationEnabled()
                        ? socialVerificationService.verifyDue(
                                Duration.ofDays(properties.getSocialVerificationMaxAgeDays()),
                                properties.getSocialVerificationBatchSize())
                        : reactor.core.publisher.Mono.just(0))
                .doFinally(signal -> jobGuard.release())
                .subscribe(
                        ignored -> LOG.info("parliament automatic sync and social verification completed"),
                        error -> LOG.error("parliament automatic sync failed: {}",
                                error.getClass().getSimpleName()));
    }
}
