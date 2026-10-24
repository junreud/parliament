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
        List<SocialAccount> socialAccounts,
        String sourcePersonNamespace,
        List<ExternalIdentifier> identifierAliases
) {
    public static final String NAAS_NAMESPACE = "OPEN_ASSEMBLY_NAAS_CD";
    public static final String MONA_NAMESPACE = "OPEN_ASSEMBLY_MONA_CD";

    public record ExternalIdentifier(String namespace, String externalId) {
        public ExternalIdentifier {
            if (namespace == null || namespace.isBlank() || externalId == null || externalId.isBlank()) {
                throw new IllegalArgumentException("identifier namespace and value are required");
            }
            namespace = namespace.trim();
            externalId = externalId.trim();
        }
    }

    /** Compatibility for callers that explicitly supply the old, untyped identity contract. */
    public PersonCandidate(String identityKey, String canonicalName, PersonKind kind,
                           String sourcePersonId, String positionTitle, String organization,
                           PersonResolutionStatus resolutionStatus, List<SocialAccount> socialAccounts) {
        this(identityKey, canonicalName, kind, sourcePersonId, positionTitle, organization,
                resolutionStatus, socialAccounts,
                resolutionStatus == PersonResolutionStatus.VERIFIED_EXTERNAL_ID && sourcePersonId != null
                        ? "OPEN_ASSEMBLY_MEMBER" : null, List.of());
    }

    public PersonCandidate {
        socialAccounts = socialAccounts == null ? List.of() : List.copyOf(socialAccounts);
        identifierAliases = identifierAliases == null ? List.of() : List.copyOf(identifierAliases);
        if (resolutionStatus != PersonResolutionStatus.VERIFIED_EXTERNAL_ID
                && (sourcePersonNamespace != null || !identifierAliases.isEmpty())) {
            throw new IllegalArgumentException("provisional names cannot own external identifiers");
        }
    }

    public List<ExternalIdentifier> identifiers() {
        if (sourcePersonNamespace == null || sourcePersonId == null) {
            return List.of();
        }
        return java.util.stream.Stream.concat(
                java.util.stream.Stream.of(new ExternalIdentifier(sourcePersonNamespace, sourcePersonId)),
                identifierAliases.stream()).distinct().toList();
    }

    public PersonCandidate withIdentityKey(String resolvedIdentityKey) {
        return new PersonCandidate(resolvedIdentityKey, canonicalName, kind, sourcePersonId,
                positionTitle, organization, resolutionStatus, socialAccounts,
                sourcePersonNamespace, identifierAliases);
    }

    public PersonCandidate withSocialAccounts(List<SocialAccount> accounts) {
        return new PersonCandidate(identityKey, canonicalName, kind, sourcePersonId,
                positionTitle, organization, resolutionStatus, accounts, sourcePersonNamespace, identifierAliases);
    }
}
