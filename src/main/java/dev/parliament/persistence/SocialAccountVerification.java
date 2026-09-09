package dev.parliament.persistence;

import dev.parliament.domain.SocialUrlVerificationStatus;

import java.time.Instant;

public record SocialAccountVerification(
        SocialAccountVerificationTarget target,
        SocialUrlVerificationStatus status,
        Integer httpStatus,
        String resolvedUrl,
        String errorCode,
        Instant verifiedAt
) {
}
