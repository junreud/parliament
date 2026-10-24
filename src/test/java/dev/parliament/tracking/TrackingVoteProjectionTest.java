package dev.parliament.tracking;

import static org.assertj.core.api.Assertions.*;

import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.List;

class TrackingVoteProjectionTest {
    @Test
    void sessionIncludesAll300PublishedParticipantsAndSourceVersions() {
        List<Activity> rows = new ArrayList<>();
        Activity base =
                TrackingPolicyTest.activity("https://open.assembly.go.kr/x", "row=base", "unknown");
        for (int i = 0; i < 300; i++)
            rows.add(
                    new Activity(
                            "row_" + i,
                            "vote",
                            base.title(),
                            null,
                            "voted",
                            List.of("p_" + i),
                            List.of("housing"),
                            base.billId(),
                            base.occurredAt(),
                            base.publishedAt(),
                            base.collectedAt(),
                            base.sourceUrl(),
                            List.of(
                                    new Activity.Evidence(
                                            "ev_" + i,
                                            base.sourceUrl(),
                                            null,
                                            "row=" + i,
                                            "raw_" + i)),
                            List.of(
                                    new Activity.Vote(
                                            "p_" + i,
                                            "표본 " + i,
                                            i == 0 ? "unknown" : "yes",
                                            "session_1")),
                            base.coverage(),
                            false,
                            "v_" + i));
        Activity combined = TrackingVoteProjection.combine("source", "bill", "session", rows);
        assertThat(combined.votes()).hasSize(300);
        assertThat(combined.evidence()).hasSize(300);
        assertThat(combined.votes().get(0).result()).isEqualTo("unknown");
        java.util.Collections.reverse(rows);
        assertThat(TrackingVoteProjection.combine("source", "bill", "session", rows).version())
                .isEqualTo(combined.version());
    }

    @Test
    void conflictingParticipantIsUnavailableRatherThanArbitrarilyChoosingPosition() {
        var unknown =
                TrackingPolicyTest.activity("https://open.assembly.go.kr/x", "row=1", "unknown");
        var yes = TrackingPolicyTest.activity("https://open.assembly.go.kr/x", "row=2", "yes");
        assertThatThrownBy(
                        () ->
                                TrackingVoteProjection.combine(
                                        "source", "bill", "session", List.of(unknown, yes)))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("conflicting individual");
    }
}
