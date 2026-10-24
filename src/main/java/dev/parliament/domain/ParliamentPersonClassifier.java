package dev.parliament.domain;

import dev.parliament.util.TextUtil;

import java.text.Normalizer;
import java.util.List;
import java.util.Locale;
import java.util.Set;

public class ParliamentPersonClassifier {
    private static final Set<String> PUBLIC_OFFICIAL_TITLES = Set.of(
            "대통령", "국무총리", "부총리", "장관", "차관", "청장", "처장", "공무원",
            "국무위원", "정부위원", "비서실장", "수석비서관", "검찰총장", "경찰청장"
    );

    /** Legacy untyped identity entry point. New source normalizers must use the explicit namespace overload. */
    public PersonCandidate classify(
            String name,
            String sourcePersonId,
            String positionTitle,
            String organization,
            boolean knownAssemblyMember
    ) {
        return classify(name, sourcePersonId, "OPEN_ASSEMBLY_MEMBER", positionTitle, organization,
                knownAssemblyMember, List.of());
    }

    /** The caller verifies the ID/name field pairing and any roster aliases before classification. */
    public PersonCandidate classify(
            String name, String sourcePersonId, String sourcePersonNamespace,
            String positionTitle, String organization, boolean knownAssemblyMember,
            List<PersonCandidate.ExternalIdentifier> aliases
    ) {
        String canonicalName = normalizeName(name);
        if (canonicalName.isBlank()) {
            throw new IllegalArgumentException("person name must not be blank");
        }

        boolean verifiedMember = knownAssemblyMember && sourcePersonId != null && !sourcePersonId.isBlank()
                && sourcePersonNamespace != null && !sourcePersonNamespace.isBlank();
        PersonKind kind = verifiedMember
                ? PersonKind.LEGISLATOR
                : isPublicOfficial(positionTitle) ? PersonKind.PUBLIC_OFFICIAL : PersonKind.OTHER;
        String identityKey = verifiedMember
                ? "OPEN_ASSEMBLY_MEMBER".equals(sourcePersonNamespace)
                    ? "assembly-member:" + sourcePersonId.trim().toLowerCase(Locale.ROOT)
                    : "assembly-member:" + sourcePersonNamespace + ":" + TextUtil.textSha1(sourcePersonId.trim())
                : "provisional-person:" + TextUtil.textSha1(String.join("|",
                        canonicalName, identityPart(positionTitle), identityPart(organization)));

        return new PersonCandidate(
                identityKey,
                canonicalName,
                kind,
                verifiedMember ? blankToNull(sourcePersonId) : null,
                blankToNull(positionTitle),
                blankToNull(organization),
                verifiedMember
                        ? PersonResolutionStatus.VERIFIED_EXTERNAL_ID
                        : PersonResolutionStatus.PROVISIONAL_NAME_MATCH,
                List.of(),
                verifiedMember ? sourcePersonNamespace : null,
                verifiedMember ? aliases : List.of()
        );
    }

    private boolean isPublicOfficial(String positionTitle) {
        if (positionTitle == null || positionTitle.isBlank()) {
            return false;
        }
        return PUBLIC_OFFICIAL_TITLES.stream().anyMatch(positionTitle::contains);
    }

    private String normalizeName(String value) {
        if (value == null) {
            return "";
        }
        return Normalizer.normalize(value, Normalizer.Form.NFKC).replaceAll("\\s+", "").trim();
    }

    private String blankToNull(String value) {
        return value == null || value.isBlank() ? null : value.trim();
    }

    private String identityPart(String value) {
        return value == null ? "" : Normalizer.normalize(value, Normalizer.Form.NFKC).trim();
    }
}
