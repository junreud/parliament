package dev.parliament.domain;

public record SocialAccount(
        SocialPlatform platform,
        String url,
        String handle,
        boolean primary,
        SocialVerificationStatus verificationStatus
) {
}

