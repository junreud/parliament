package dev.parliament.domain;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class ParliamentPersonClassifierTest {

    private final ParliamentPersonClassifier classifier = new ParliamentPersonClassifier();

    @Test
    void assemblyIdentityTakesPriorityOverPositionTitle() {
        PersonCandidate person = classifier.classify(
                " 홍 길 동 ", "mona-123", "위원장", "국회", true);

        assertThat(person.canonicalName()).isEqualTo("홍길동");
        assertThat(person.identityKey()).isEqualTo("assembly-member:mona-123");
        assertThat(person.kind()).isEqualTo(PersonKind.LEGISLATOR);
    }

    @Test
    void primeMinisterAndCabinetTitlesAreGovernmentOfficials() {
        assertThat(classifier.classify("김총리", null, "국무총리", "국무조정실", false).kind())
                .isEqualTo(PersonKind.PUBLIC_OFFICIAL);
        assertThat(classifier.classify("박장관", null, "보건복지부 장관", "보건복지부", false).kind())
                .isEqualTo(PersonKind.PUBLIC_OFFICIAL);
    }

    @Test
    void unrecognisedThirdPartyIsKeptAsOther() {
        PersonCandidate witness = classifier.classify("이증인", null, "참고인", "민간연구소", false);

        assertThat(witness.kind()).isEqualTo(PersonKind.OTHER);
        assertThat(witness.identityKey()).startsWith("provisional-person:");
        assertThat(witness.resolutionStatus()).isEqualTo(PersonResolutionStatus.PROVISIONAL_NAME_MATCH);
    }

    @Test
    void sameNameWithDifferentContextDoesNotShareProvisionalIdentity() {
        PersonCandidate witness = classifier.classify("김민수", null, "참고인", "민간연구소", false);
        PersonCandidate official = classifier.classify("김민수", null, "과장", "기획재정부", false);

        assertThat(witness.identityKey()).isNotEqualTo(official.identityKey());
    }
}
