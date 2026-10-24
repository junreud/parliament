package dev.parliament.tracking;

import static org.assertj.core.api.Assertions.*;

import org.junit.jupiter.api.Test;

class KnowledgeSourcePolicyTest {
    @Test
    void acceptsTheOfficialProfileAndChildSupportExecutionEvidence() {
        assertThatCode(() -> TrackingPolicy.officialUrl(
                "https://ampos.nanet.go.kr/activityCongressDetail.do?congress_no=G1899720"))
                .doesNotThrowAnyException();
        assertThatCode(() -> TrackingPolicy.officialUrl(
                "https://www.mogef.go.kr/sp/fam/sp_fam_f017.do"))
                .doesNotThrowAnyException();
        assertThatCode(() -> TrackingPolicy.officialUrl(
                "https://www.hscity.go.kr/mayor/index.do"))
                .doesNotThrowAnyException();
        assertThatCode(() -> TrackingPolicy.officialUrl(
                "https://www.balance.go.kr/base/board/read?boardNo=9778"))
                .doesNotThrowAnyException();
    }

    @Test
    void rejectsDeceptiveHostsCredentialsAndUnapprovedSources() {
        for (String url : new String[] {"https://mogef.go.kr.attacker.example/x",
                "https://user@www.mogef.go.kr/x", "https://127.0.0.1/x",
                "http://www.mogef.go.kr/x", "https://news.example/article",
                "https://www.hscity.go.kr.evil.example/x",
                "https://evil.www.hscity.go.kr/x",
                "https://www.balance.go.kr.evil.example/x",
                "https://evil.www.balance.go.kr/x"}) {
            assertThatThrownBy(() -> TrackingPolicy.officialUrl(url))
                    .isInstanceOf(IllegalArgumentException.class);
        }
    }
}
