package dev.parliament.tracking;

import static org.assertj.core.api.Assertions.*;

import org.junit.jupiter.api.Test;

import java.time.Instant;
import java.util.List;

class TrackingPolicyTest {
    private final TrackingPolicy policy = new TrackingPolicy();
    private final Instant now = Instant.parse("2026-10-07T00:00:00Z");

    @Test
    void acceptsEvidenceWithSpecificOfficialLocator() {
        assertThatCode(
                        () ->
                                policy.validate(
                                        activity(
                                                "https://open.assembly.go.kr/portal/openapi/x",
                                                "BILL_ID=b1",
                                                "unknown")))
                .doesNotThrowAnyException();
    }

    @Test
    void rejectsLookalikeHostAndCredentialsAndMissingLocator() {
        for (String url :
                List.of(
                        "https://assembly.go.kr.evil.test/x",
                        "https://user@open.assembly.go.kr/x",
                        "http://open.assembly.go.kr/x")) {
            assertThatThrownBy(() -> policy.validate(activity(url, "BILL_ID=b1", "unknown")))
                    .isInstanceOf(IllegalArgumentException.class);
        }
        assertThatThrownBy(
                        () ->
                                policy.validate(
                                        activity("https://open.assembly.go.kr/x", "", "unknown")))
                .isInstanceOf(IllegalArgumentException.class);
    }

    @Test
    void doesNotTurnMissingVoteIntoAbsent() {
        assertThatThrownBy(
                        () ->
                                policy.validate(
                                        activity(
                                                "https://open.assembly.go.kr/x",
                                                "BILL_ID=b1",
                                                "missing")))
                .isInstanceOf(IllegalArgumentException.class);
        assertThat(
                        activity("https://open.assembly.go.kr/x", "BILL_ID=b1", "unknown")
                                .votes()
                                .get(0)
                                .result())
                .isEqualTo("unknown");
    }

    @Test
    void cursorRoundTripAndTamperedCursorFails() {
        TrackingCursor cursor = new TrackingCursor(now, "evt_one");
        assertThat(TrackingCursor.decode(cursor.encode())).isEqualTo(cursor);
        assertThatThrownBy(() -> TrackingCursor.decode("../../x"))
                .isInstanceOf(IllegalArgumentException.class);
    }

    @Test
    void projectionCursorCannotBeReusedForAnotherSource() {
        var cursor = new TrackingProjectionCursor("verified", "bill", "record_1", null, null);
        assertThat(TrackingProjectionCursor.decode(cursor.encode(), "verified", "bill"))
                .isEqualTo(cursor);
        assertThatThrownBy(() -> TrackingProjectionCursor.decode(cursor.encode(), "other", "bill"))
                .isInstanceOf(IllegalArgumentException.class);
    }

    @Test
    void emptyAdminKeyFailsClosed() {
        assertThatThrownBy(() -> new TrackingAdminAuthorization(""))
                .isInstanceOf(IllegalStateException.class);
        TrackingAdminAuthorization auth = new TrackingAdminAuthorization("test-only-secret");
        assertThatCode(() -> auth.authorize("test-only-secret")).doesNotThrowAnyException();
        assertThatThrownBy(() -> auth.authorize("different"))
                .isInstanceOf(org.springframework.web.server.ResponseStatusException.class);
    }

    static Activity activity(String url, String locator, String vote) {
        Instant now = Instant.parse("2026-10-07T00:00:00Z");
        return new Activity(
                "evt_one",
                "vote",
                "법안 표결",
                null,
                "voted",
                List.of("p_one"),
                List.of("housing"),
                "b_one",
                now,
                now,
                now,
                url,
                List.of(new Activity.Evidence("ev_one", url, "원문", locator, "hash1")),
                List.of(new Activity.Vote("p_one", "표본 인물", vote, "s_one")),
                "individual_votes",
                false,
                "v1");
    }
}
