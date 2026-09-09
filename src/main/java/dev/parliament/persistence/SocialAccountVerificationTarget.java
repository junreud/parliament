package dev.parliament.persistence;

import dev.parliament.domain.SocialPlatform;

public record SocialAccountVerificationTarget(
        String identityKey,
        SocialPlatform platform,
        String urlHash,
        String canonicalUrl
) {
}
