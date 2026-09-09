package dev.parliament.service;

import dev.parliament.config.ParliamentIngestionProperties;
import org.junit.jupiter.api.Test;
import reactor.core.publisher.Mono;

import java.util.List;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class ParliamentAutomaticSyncSchedulerTest {

    @Test
    void runsIncrementalSyncThenDueSocialVerification() {
        ParliamentIngestionService ingestion = mock(ParliamentIngestionService.class);
        ParliamentSocialVerificationService social = mock(ParliamentSocialVerificationService.class);
        ParliamentIngestionProperties properties = new ParliamentIngestionProperties();
        properties.setIncrementalPageSize(50);
        properties.setIncrementalMaxPages(20);
        properties.setSocialVerificationMaxAgeDays(3);
        properties.setSocialVerificationBatchSize(40);
        when(ingestion.synchronize(any())).thenReturn(Mono.just(
                new ParliamentSyncReport(java.time.Instant.EPOCH, java.time.Instant.EPOCH, List.of())));
        when(social.verifyDue(java.time.Duration.ofDays(3), 40)).thenReturn(Mono.just(7));
        ParliamentAutomaticSyncScheduler scheduler =
                new ParliamentAutomaticSyncScheduler(
                        ingestion, social, properties, new ParliamentJobGuard());

        scheduler.synchronize();

        verify(ingestion).synchronize(new ParliamentIngestionRequest(List.of(), 50, 20, true));
        verify(social).verifyDue(java.time.Duration.ofDays(3), 40);
    }

    @Test
    void doesNotOverlapRunsAndCanSkipSocialChecks() {
        ParliamentIngestionService ingestion = mock(ParliamentIngestionService.class);
        ParliamentSocialVerificationService social = mock(ParliamentSocialVerificationService.class);
        ParliamentIngestionProperties properties = new ParliamentIngestionProperties();
        properties.setSocialVerificationEnabled(false);
        when(ingestion.synchronize(any())).thenReturn(Mono.never());
        ParliamentAutomaticSyncScheduler scheduler =
                new ParliamentAutomaticSyncScheduler(
                        ingestion, social, properties, new ParliamentJobGuard());

        scheduler.synchronize();
        scheduler.synchronize();

        verify(ingestion, times(1)).synchronize(any());
        verify(social, times(0)).verifyDue(any(), anyInt());
    }
}
