package dev.parliament.knowledge;

import static org.assertj.core.api.Assertions.*;
import static dev.parliament.knowledge.KnowledgeBatch.*;
import java.time.Instant;
import java.util.List;
import org.junit.jupiter.api.Test;

class PublicLawsTest {
    static Document law(String license, String effectiveDate, String recordKey) {
        var segments = List.of(
            new Segment("title", "아동수당법", "json:법령.기본정보.법령명_한글", List.of()),
            new Segment("lawid", "013103", "json:법령.기본정보.법령ID", List.of()),
            new Segment("promulgated", "20260609", "json:법령.기본정보.공포일자", List.of()),
            new Segment("effective", effectiveDate, "json:법령.기본정보.시행일자", List.of()),
            new Segment("agency", "보건복지부", "json:법령.기본정보.소관부처.content", List.of()),
            new Segment("number", "21777", "json:법령.기본정보.공포번호", List.of()));
        return new Document("law_013103_286729", "a".repeat(64), "law", recordKey,
            "https://www.law.go.kr/DRF/lawService.do?target=law&MST=286729&type=JSON",
            "아동수당법", "json", "available", license, Instant.parse("2026-06-08T15:00:00Z"),
            Instant.parse("2026-10-09T08:00:00Z"), "private/raw.json", "law_public_metadata_v1",
            segments, "law_observation", "date");
    }
    @Test void readsDatesFromPinnedMetadataAndBuildsCredentialFreeVersionLink() {
        var item = PublicLaws.project(law("allowed", "20260910", "013103:286729")).orElseThrow();
        assertThat(item.promulgatedDate()).hasToString("2026-06-09");
        assertThat(item.effectiveDate()).hasToString("2026-09-10");
        assertThat(item.sourceUrl()).isEqualTo("https://www.law.go.kr/LSW/lsInfoP.do?lsiSeq=286729");
        assertThat(item.agency()).isEqualTo("보건복지부");
        assertThat(item.evidence()).hasSize(6);
    }
    @Test void neverExposesUnknownOrRestrictedRights() {
        assertThat(PublicLaws.project(law("unknown", "20260910", "013103:286729"))).isEmpty();
        assertThat(PublicLaws.project(law("restricted", "20260910", "013103:286729"))).isEmpty();
    }
    @Test void rejectsWrongLawIdentityAndInvalidCalendarDate() {
        assertThat(PublicLaws.project(law("allowed", "20260230", "013103:286729"))).isEmpty();
        assertThat(PublicLaws.project(law("allowed", "20260910", "013145:286729"))).isEmpty();
        assertThat(PublicLaws.project(law("allowed", "20260910", "013103:../../admin"))).isEmpty();
    }
    @Test void preservesUnknownEffectiveDate() {
        assertThat(PublicLaws.project(law("allowed", "00000000", "013103:286729")).orElseThrow().effectiveDate()).isNull();
    }
}
