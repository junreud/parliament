package dev.parliament.domain;

import java.util.List;

public record PersonCandidate(
        String identityKey,
        String canonicalName,
        PersonKind kind,
        String sourcePersonId,
        String positionTitle,
        String organization,
        PersonResolutionStatus resolutionStatus,
        List<SocialAccount> socialAccounts
) {
    public PersonCandidate {
        socialAccounts = socialAccounts == null ? List.of() : List.copyOf(socialAccounts);
    }

    public PersonCandidate withSocialAccounts(List<SocialAccount> accounts) {
        return new PersonCandidate(identityKey, canonicalName, kind, sourcePersonId,
                positionTitle, organization, resolutionStatus, accounts);
    }
}
