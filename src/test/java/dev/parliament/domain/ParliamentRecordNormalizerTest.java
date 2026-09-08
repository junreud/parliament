package dev.parliament.domain;

import com.fasterxml.jackson.databind.ObjectMapper;
import dev.parliament.config.ParliamentCollectionMode;
import dev.parliament.config.ParliamentMediaType;
import dev.parliament.config.ParliamentSourceDefinition;
import org.junit.jupiter.api.Test;

import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

class ParliamentRecordNormalizerTest {

    private final ParliamentRecordNormalizer normalizer = new ParliamentRecordNormalizer(new ObjectMapper());

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
}
