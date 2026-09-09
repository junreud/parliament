package dev.parliament.domain;

public enum SocialUrlVerificationStatus {
    UNCHECKED,
    REACHABLE,
    REDIRECTED,
    NOT_FOUND,
    TEMPORARY_FAILURE,
    REJECTED
}
