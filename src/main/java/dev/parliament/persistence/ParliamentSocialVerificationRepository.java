package dev.parliament.persistence;

import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;

import java.time.Instant;

public interface ParliamentSocialVerificationRepository {
    Flux<SocialAccountVerificationTarget> findDue(Instant verifiedBefore, int limit);

    Mono<Void> saveVerification(SocialAccountVerification verification);
}
