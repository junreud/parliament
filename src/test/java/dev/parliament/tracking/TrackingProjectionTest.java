package dev.parliament.tracking;

import static org.assertj.core.api.Assertions.*;

import com.fasterxml.jackson.databind.ObjectMapper;

import org.junit.jupiter.api.Test;

import java.time.Instant;
import java.util.List;
import java.util.Map;

class TrackingProjectionTest {
    private final ObjectMapper mapper = new ObjectMapper();

    @Test
    void explicitVerifiedBillContractKeepsRawVersionAndDateOnlyCoverage() throws Exception {
        var contract =
                new TrackingProjection.Contract(
                        "bills",
                        "bill",
                        true,
                        Map.of(
                                "id",
                                "BILL_ID",
                                "title",
                                "BILL_NAME",
                                "url",
                                "LINK_URL",
                                "publishedAt",
                                "PROPOSE_DT",
                                "stage",
                                "PROC_RESULT"),
                        Map.of("접수", "proposed"),
                        Map.of(),
                        null,
                        List.of("housing"),
                        50);
        var raw =
                mapper.readTree(
                        "{\"BILL_ID\":\"B1\",\"BILL_NAME\":\"표본"
                            + " 법안\",\"LINK_URL\":\"https://likms.assembly.go.kr/bill/billDetail.do?billId=B1\",\"PROPOSE_DT\":\"2026-10-01\",\"PROC_RESULT\":\"접수\"}");
        Activity a =
                TrackingProjection.toActivity(
                        contract,
                        "r1",
                        "rawhash",
                        raw,
                        Instant.parse("2026-10-07T01:00:00Z"),
                        List.of());
        assertThat(a.occurredAt()).isNull();
        assertThat(a.publishedAt()).isEqualTo(Instant.parse("2026-09-30T15:00:00Z"));
        assertThat(a.evidence().get(0).sourceVersion()).isEqualTo("rawhash");
        assertThat(a.coverage()).contains("시각");
        assertThat(a.stage()).isEqualTo("proposed");
    }

    @Test
    void unknownStageRemainsUnknownAndMissingPublicationDoesNotUseObservedTime() throws Exception {
        var c =
                new TrackingProjection.Contract(
                        "bills",
                        "bill",
                        true,
                        Map.of("id", "ID", "title", "TITLE", "url", "URL", "publishedAt", "DATE"),
                        Map.of(),
                        Map.of(),
                        null,
                        List.of(),
                        20);
        var raw =
                mapper.readTree(
                        "{\"ID\":\"x\",\"TITLE\":\"제목\",\"URL\":\"https://open.assembly.go.kr/x\"}");
        assertThatThrownBy(
                        () ->
                                TrackingProjection.toActivity(
                                        c, "r1", "hash", raw, Instant.now(), List.of()))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("publication");
    }
}
