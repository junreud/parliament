package dev.parliament.domain;

import java.text.Normalizer;
import java.util.Locale;
import java.util.List;
import java.util.Set;

public class ParliamentPersonClassifier {
    private static final Set<String> PUBLIC_OFFICIAL_TITLES = Set.of(
            "대통령", "국무총리", "부총리", "장관", "차관", "청장", "처장", "공무원",
            "국무위원", "정부위원", "비서실장", "수석비서관", "검찰총장", "경찰청장"
    );

    public PersonCandidate classify(
            String name,
            String sourcePersonId,
            String positionTitle,
            String organization,
            boolean knownAssemblyMember
    ) {
        String canonicalName = normalizeName(name);
        if (canonicalName.isBlank()) {
            throw new IllegalArgumentException("person name must not be blank");
        }

        boolean verifiedMember = knownAssemblyMember && sourcePersonId != null && !sourcePersonId.isBlank();
        PersonKind kind = verifiedMember
                ? PersonKind.LEGISLATOR
                : isPublicOfficial(positionTitle) ? PersonKind.PUBLIC_OFFICIAL : PersonKind.OTHER;
        String identityKey = verifiedMember
                ? "assembly-member:" + sourcePersonId.trim().toLowerCase(Locale.ROOT)
                : "provisional-name:" + canonicalName;

        return new PersonCandidate(
                identityKey,
                canonicalName,
                kind,
                blankToNull(sourcePersonId),
                blankToNull(positionTitle),
                blankToNull(organization),
                verifiedMember
                        ? PersonResolutionStatus.VERIFIED_EXTERNAL_ID
                        : PersonResolutionStatus.PROVISIONAL_NAME_MATCH,
                List.of()
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
}
