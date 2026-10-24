package dev.parliament.domain;

import com.fasterxml.jackson.databind.ObjectMapper;
import dev.parliament.config.ParliamentCollectionMode;
import dev.parliament.config.ParliamentMediaType;
import dev.parliament.config.ParliamentSourceDefinition;
import org.junit.jupiter.api.Test;

import java.util.Map;
import java.util.LinkedHashMap;

import static org.assertj.core.api.Assertions.assertThat;

class ParliamentRecordNormalizerTest {

    private final ParliamentRecordNormalizer normalizer = new ParliamentRecordNormalizer(new ObjectMapper());

    @Test
    void separatesIdentifierKindsAndPreservesExactCase() {
        var source = memberSource();
        var naas = normalizer.normalize(source, Map.of("NAAS_CD", "AbC", "NAAS_NM", "홍길동"))
                .people().get(0);
        var mona = normalizer.normalize(source, Map.of("MONA_CD", "AbC", "HG_NM", "홍길동"))
                .people().get(0);
        var differentCase = normalizer.normalize(source, Map.of("NAAS_CD", "abc", "NAAS_NM", "홍길동"))
                .people().get(0);
        assertThat(naas.identityKey()).isNotEqualTo(mona.identityKey()).isNotEqualTo(differentCase.identityKey());
        assertThat(naas.sourcePersonId()).isEqualTo("AbC");
    }

    @Test
    void doesNotAttachMemberIdToUnrelatedSpeakerOrGovernmentName() {
        var people = normalizer.normalize(memberSource(), Map.of(
                "NAAS_CD", "A001", "NAAS_NM", "홍의원", "SPEAKER_NM", "김장관"))
                .people();
        assertThat(people).hasSize(2);
        assertThat(people.get(1).sourcePersonId()).isNull();
        assertThat(people.get(1).resolutionStatus()).isEqualTo(PersonResolutionStatus.PROVISIONAL_NAME_MATCH);
        var government = new ParliamentSourceDefinition("gov", "GOV", "정부인사", null,
                ParliamentMediaType.DATA, ParliamentCollectionMode.PAGE, Map.of());
        var minister = normalizer.normalize(government, Map.of(
                "MEMBER_ID", "A001", "PERSON_NM", "김장관", "ROLE", "장관")).people().get(0);
        assertThat(minister.kind()).isEqualTo(PersonKind.PUBLIC_OFFICIAL);
        assertThat(minister.sourcePersonId()).isNull();
    }

    @Test
    void aliasesOnlyMatchingNamesOnVerifiedRosterRows() {
        var row = Map.<String, Object>of("NAAS_CD", "A001", "NAAS_NM", "홍 길 동",
                "MONA_CD", "M001", "HG_NM", "홍길동");
        assertThat(normalizer.normalize(memberSource(), row).people()).singleElement().satisfies(person -> {
            assertThat(person.identifiers()).containsExactly(
                    new PersonCandidate.ExternalIdentifier(PersonCandidate.NAAS_NAMESPACE, "A001"),
                    new PersonCandidate.ExternalIdentifier(PersonCandidate.MONA_NAMESPACE, "M001"));
        });
        var conflicted = normalizer.normalize(memberSource(), Map.of(
                "NAAS_CD", "A001", "NAAS_NM", "홍길동", "MONA_CD", "M001", "HG_NM", "김다른"));
        assertThat(conflicted.people()).hasSize(2);
        assertThat(conflicted.people().get(1).sourcePersonId()).isNull();
        var votes = new ParliamentSourceDefinition("votes", "VOTES", "국회의원 표결", null,
                ParliamentMediaType.DATA, ParliamentCollectionMode.PAGE, Map.of());
        // A non-roster document does not prove two ID schemes identify the same person.
        assertThat(normalizer.normalize(votes, row).people()).hasSize(2);
        assertThat(normalizer.normalize(votes, row).people().get(0).identifierAliases()).isEmpty();
    }

    private ParliamentSourceDefinition memberSource() {
        return new ParliamentSourceDefinition("allnamember", "ALLNAMEMBER", "국회의원 정보 통합 API", null,
                ParliamentMediaType.DATA, ParliamentCollectionMode.PAGE, Map.of());
    }

    @Test
    void memberRecordCarriesOfficialSocialAccountsIntoPersonMapping() {
        ParliamentSourceDefinition source = new ParliamentSourceDefinition(
                "members", "ALLNAMEMBER", "국회의원 정보 통합 API", "15126133",
                ParliamentMediaType.DATA, ParliamentCollectionMode.PAGE, Map.of());

        NormalizedParliamentRecord record = normalizer.normalize(source, Map.of(
                "NAAS_CD", "A001",
                "NAAS_NM", "홍길동",
                "PLPT_NM", "미래정당",
                "TWITTER_URL", "https://x.com/hong",
                "YOUTUBE_URL", "https://youtube.com/@hongtv"
        ));

        assertThat(record.recordKey()).isEqualTo("A001");
        assertThat(record.people()).singleElement().satisfies(person -> {
            assertThat(person.kind()).isEqualTo(PersonKind.LEGISLATOR);
            assertThat(person.positionTitle()).isEqualTo("국회의원");
            assertThat(person.organization()).isEqualTo("미래정당");
            assertThat(person.socialAccounts()).extracting(SocialAccount::platform)
                    .containsExactlyInAnyOrder(SocialPlatform.X, SocialPlatform.YOUTUBE);
        });
    }

    @Test
    void recordWithoutStableIdUsesDeterministicContentKey() {
        ParliamentSourceDefinition source = new ParliamentSourceDefinition(
                "hearing", "VCONFCHCONFLIST", "청문회 회의록", "15126145",
                ParliamentMediaType.DATA, ParliamentCollectionMode.PAGE, Map.of());
        Map<String, Object> row = Map.of("PERSON_NM", "이증인", "ROLE", "참고인");

        assertThat(normalizer.normalize(source, row).recordKey())
                .isEqualTo(normalizer.normalize(source, row).recordKey());
    }

    @Test
    void keepsIndividualVotesAndRoundsSeparateWithoutUsingVoteResultInIdentity() {
        ParliamentSourceDefinition source = new ParliamentSourceDefinition(
                "nojepdqqaweusdfbi", "nojepdqqaweusdfbi", "국회의원 본회의 표결정보", null,
                ParliamentMediaType.DATA, ParliamentCollectionMode.PAGE, Map.of("AGE", "22"));
        Map<String, Object> row = Map.of("BILL_ID", "bill-1", "MONA_CD", "member-1",
                "CONF_ID", "meeting-1", "RESULT_VOTE_MOD", "찬성");
        String original = normalizer.normalize(source, row).recordKey();
        assertThat(normalizer.normalize(source, Map.of("BILL_ID", "bill-1", "MONA_CD", "member-2",
                "CONF_ID", "meeting-1", "RESULT_VOTE_MOD", "찬성")).recordKey()).isNotEqualTo(original);
        assertThat(normalizer.normalize(source, Map.of("BILL_ID", "bill-1", "MONA_CD", "member-1",
                "CONF_ID", "meeting-2", "RESULT_VOTE_MOD", "찬성")).recordKey()).isNotEqualTo(original);
        assertThat(normalizer.normalize(source, Map.of("BILL_ID", "bill-1", "MONA_CD", "member-1",
                "CONF_ID", "meeting-1", "RESULT_VOTE_MOD", "반대")).recordKey()).isEqualTo(original);
    }

    @Test
    void canonicalHashDoesNotChangeWhenJsonObjectOrderChanges() {
        ParliamentSourceDefinition source = new ParliamentSourceDefinition(
                "sample", "sample", "표본", null, ParliamentMediaType.DATA,
                ParliamentCollectionMode.PAGE, Map.of());
        Map<String, Object> first = new LinkedHashMap<>();
        first.put("BILL_ID", "bill-1");
        first.put("DETAIL", Map.of("a", "value", "b", 2));
        Map<String, Object> second = new LinkedHashMap<>();
        second.put("DETAIL", Map.of("b", 2, "a", "value"));
        second.put("BILL_ID", "bill-1");
        assertThat(normalizer.normalize(source, first).payloadHash())
                .isEqualTo(normalizer.normalize(source, second).payloadHash());
    }

    @Test
    void retainsSeparateBillMeetingRowsAndUnknownMultiRowPayloads() {
        ParliamentSourceDefinition source = new ParliamentSourceDefinition(
                "vconfbilllist", "VCONFBILLLIST", "회의별 안건목록", null,
                ParliamentMediaType.DATA, ParliamentCollectionMode.PAGE, Map.of());
        assertThat(normalizer.normalize(source, Map.of("BILL_ID", "b1", "CONF_ID", "c1")).recordKey())
                .isNotEqualTo(normalizer.normalize(source, Map.of("BILL_ID", "b1", "CONF_ID", "c2")).recordKey());
    }
}
