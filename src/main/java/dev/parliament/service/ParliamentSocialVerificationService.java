package dev.parliament.service;

import dev.parliament.domain.SocialUrlVerificationStatus;
import dev.parliament.persistence.ParliamentSocialVerificationRepository;
import dev.parliament.persistence.SocialAccountVerification;
import dev.parliament.persistence.SocialAccountVerificationTarget;
import reactor.core.publisher.Mono;

import java.net.URI;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;

public class ParliamentSocialVerificationService {
    private static final int MAX_REDIRECTS = 3;
    private static final int VERIFY_CONCURRENCY = 8;
    private static final Duration REQUEST_TIMEOUT = Duration.ofSeconds(15);

    private final SocialLinkClient client;
    private final ParliamentSocialVerificationRepository repository;
    private final ParliamentSocialUrlPolicy urlPolicy;
    private final Clock clock;

    public ParliamentSocialVerificationService(
            SocialLinkClient client,
            ParliamentSocialVerificationRepository repository,
            ParliamentSocialUrlPolicy urlPolicy,
            Clock clock
    ) {
        this.client = client;
        this.repository = repository;
        this.urlPolicy = urlPolicy;
        this.clock = clock;
    }

    public Mono<Integer> verifyDue(Duration maxAge, int limit) {
        if (maxAge == null || maxAge.isNegative() || maxAge.isZero()) {
            return Mono.error(new IllegalArgumentException("maxAge must be positive"));
        }
        if (limit < 1 || limit > 10_000) {
            return Mono.error(new IllegalArgumentException("limit must be between 1 and 10000"));
        }
        Instant verifiedBefore = clock.instant().minus(maxAge);
        return repository.findDue(verifiedBefore, limit)
                .flatMap(target -> verify(target)
                        .flatMap(repository::saveVerification)
                        .thenReturn(1), VERIFY_CONCURRENCY)
                .reduce(0, Integer::sum);
    }

    private Mono<SocialAccountVerification> verify(SocialAccountVerificationTarget target) {
        try {
            URI initial = urlPolicy.requireAllowed(target.canonicalUrl());
            return follow(target, initial, 0, false)
                    .onErrorResume(error -> Mono.just(result(
                            target, SocialUrlVerificationStatus.TEMPORARY_FAILURE,
                            null, initial.toString(), error.getClass().getSimpleName())));
        } catch (IllegalArgumentException error) {
            return Mono.just(result(
                    target, SocialUrlVerificationStatus.REJECTED,
                    null, null, "URL_POLICY_REJECTED"));
        }
    }

    private Mono<SocialAccountVerification> follow(
            SocialAccountVerificationTarget target,
            URI uri,
            int redirects,
            boolean redirected
    ) {
        return client.probe(uri).timeout(REQUEST_TIMEOUT).flatMap(probe -> {
            int status = probe.statusCode();
            if (status >= 300 && status < 400 && probe.location() != null) {
                if (redirects >= MAX_REDIRECTS) {
                    return Mono.just(result(target, SocialUrlVerificationStatus.REJECTED,
                            status, uri.toString(), "TOO_MANY_REDIRECTS"));
                }
                URI next;
                try {
                    next = urlPolicy.requireAllowed(uri.resolve(probe.location()).toString());
                } catch (IllegalArgumentException error) {
                    return Mono.just(result(target, SocialUrlVerificationStatus.REJECTED,
                            status, null, "REDIRECT_POLICY_REJECTED"));
                }
                return follow(target, next, redirects + 1, true);
            }
            if (status >= 200 && status < 300 || status == 401 || status == 403) {
                return Mono.just(result(target,
                        redirected ? SocialUrlVerificationStatus.REDIRECTED
                                : SocialUrlVerificationStatus.REACHABLE,
                        status, uri.toString(), null));
            }
            if (status == 404 || status == 410) {
                return Mono.just(result(target, SocialUrlVerificationStatus.NOT_FOUND,
                        status, uri.toString(), null));
            }
            if (status >= 400 && status < 500 && status != 429) {
                return Mono.just(result(target, SocialUrlVerificationStatus.REJECTED,
                        status, uri.toString(), "HTTP_" + status));
            }
            return Mono.just(result(target, SocialUrlVerificationStatus.TEMPORARY_FAILURE,
                    status, uri.toString(), "HTTP_" + status));
        });
    }

    private SocialAccountVerification result(
            SocialAccountVerificationTarget target,
            SocialUrlVerificationStatus status,
            Integer httpStatus,
            String resolvedUrl,
            String errorCode
    ) {
        return new SocialAccountVerification(
                target, status, httpStatus, resolvedUrl, errorCode, clock.instant());
    }
}
