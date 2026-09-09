package dev.parliament.service;

import dev.parliament.domain.SocialPlatform;
import dev.parliament.domain.SocialUrlVerificationStatus;
import dev.parliament.persistence.ParliamentSocialVerificationRepository;
import dev.parliament.persistence.SocialAccountVerification;
import dev.parliament.persistence.SocialAccountVerificationTarget;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;
import reactor.test.StepVerifier;

import java.net.URI;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneOffset;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class ParliamentSocialVerificationServiceTest {
    @Mock private SocialLinkClient client;
    @Mock private ParliamentSocialVerificationRepository repository;

    private ParliamentSocialVerificationService service;

    @BeforeEach
    void setUp() {
        service = new ParliamentSocialVerificationService(
                client,
                repository,
                new ParliamentSocialUrlPolicy(),
                Clock.fixed(Instant.parse("2026-09-09T10:00:00Z"), ZoneOffset.UTC));
    }

    @Test
    void verifiesAllowedRedirectsAndStoresTheResolvedAddress() {
        SocialAccountVerificationTarget target = new SocialAccountVerificationTarget(
                "assembly-member:a1", SocialPlatform.X, "hash", "https://x.com/member");
        when(repository.findDue(Instant.parse("2026-09-02T10:00:00Z"), 10))
                .thenReturn(Flux.just(target));
        when(client.probe(URI.create("https://x.com/member")))
                .thenReturn(Mono.just(new SocialLinkProbe(301, "https://twitter.com/member")));
        when(client.probe(URI.create("https://twitter.com/member")))
                .thenReturn(Mono.just(new SocialLinkProbe(200, null)));
        when(repository.saveVerification(any())).thenReturn(Mono.empty());

        StepVerifier.create(service.verifyDue(Duration.ofDays(7), 10))
                .expectNext(1)
                .verifyComplete();

        ArgumentCaptor<SocialAccountVerification> saved =
                ArgumentCaptor.forClass(SocialAccountVerification.class);
        verify(repository).saveVerification(saved.capture());
        assertThat(saved.getValue().status()).isEqualTo(SocialUrlVerificationStatus.REDIRECTED);
        assertThat(saved.getValue().httpStatus()).isEqualTo(200);
        assertThat(saved.getValue().resolvedUrl()).isEqualTo("https://twitter.com/member");
    }

    @Test
    void rejectsLookalikeHostsBeforeAnyNetworkRequest() {
        SocialAccountVerificationTarget target = new SocialAccountVerificationTarget(
                "assembly-member:a1", SocialPlatform.X, "hash", "https://x.com.attacker.test/member");
        when(repository.findDue(Instant.parse("2026-09-02T10:00:00Z"), 10))
                .thenReturn(Flux.just(target));
        when(repository.saveVerification(any())).thenReturn(Mono.empty());

        StepVerifier.create(service.verifyDue(Duration.ofDays(7), 10))
                .expectNext(1)
                .verifyComplete();

        verify(client, never()).probe(any());
        ArgumentCaptor<SocialAccountVerification> saved =
                ArgumentCaptor.forClass(SocialAccountVerification.class);
        verify(repository).saveVerification(saved.capture());
        assertThat(saved.getValue().status()).isEqualTo(SocialUrlVerificationStatus.REJECTED);
    }

    @Test
    void classifiesPermanentClientErrorsAsRejectedInsteadOfRetryingForever() {
        SocialAccountVerificationTarget target = new SocialAccountVerificationTarget(
                "assembly-member:a1", SocialPlatform.FACEBOOK, "hash", "https://facebook.com/bad");
        when(repository.findDue(Instant.parse("2026-09-02T10:00:00Z"), 1))
                .thenReturn(Flux.just(target));
        when(client.probe(URI.create("https://facebook.com/bad")))
                .thenReturn(Mono.just(new SocialLinkProbe(400, null)));
        when(repository.saveVerification(any())).thenReturn(Mono.empty());

        StepVerifier.create(service.verifyDue(Duration.ofDays(7), 1))
                .expectNext(1)
                .verifyComplete();

        ArgumentCaptor<SocialAccountVerification> saved =
                ArgumentCaptor.forClass(SocialAccountVerification.class);
        verify(repository).saveVerification(saved.capture());
        assertThat(saved.getValue().status()).isEqualTo(SocialUrlVerificationStatus.REJECTED);
    }
}
