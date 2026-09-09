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
        if (!jobGuard.tryAcquire()) {
            return;
        }
        ParliamentIngestionRequest request = new ParliamentIngestionRequest(
                List.of(), properties.getIncrementalPageSize(),
                properties.getIncrementalMaxPages(), true);
        ingestionService.synchronize(request)
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
