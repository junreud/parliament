package dev.parliament.beta;

import java.time.Instant;
import java.util.List;
import org.junit.jupiter.api.Test;
import static org.assertj.core.api.Assertions.*;

class BetaReportTest {
    private static final Instant FROM = Instant.parse("2026-10-01T00:00:00Z");
    private static final Instant TO = Instant.parse("2026-10-31T00:00:00Z");
    private static final Instant NOW = Instant.parse("2026-10-17T00:00:00Z");

    @Test
    void requiresReadThenDepthWithinSameVisitAndOnlyMatureCohortsAreEligible() {
        var participants = List.of(person("old", "external", "2026-10-01T00:00:00Z"),
                person("new", "friend", "2026-10-16T00:00:00Z"),
                person("onlyread", "external", "2026-10-01T00:00:00Z"));
        var events = List.of(event("old", "explainer_opened", "organic", "2026-10-01T00:00:00Z"),
                event("old", "source_opened", "organic", "2026-10-01T00:01:00Z"),
                event("old", "explainer_opened", "organic", "2026-10-02T00:00:00Z"),
                event("new", "explainer_opened", "research", "2026-10-16T00:00:00Z"),
                event("new", "timeline_opened", "research", "2026-10-16T00:01:00Z"),
                event("onlyread", "explainer_opened", "organic", "2026-10-01T00:00:00Z"));
        var cohorts = BetaReport.calculate(participants, events, FROM, TO, NOW);
        var external = cohorts.stream().filter(c -> c.cohort().equals("external")).findFirst().orElseThrow();
        assertThat(external.enrolled()).isEqualTo(2);
        assertThat(external.activated()).isEqualTo(1);
        assertThat(external.organicReaders()).isEqualTo(2);
        assertThat(external.organicActivated()).isEqualTo(1);
        assertThat(external.researchActivated()).isZero();
        assertThat(external.d7Eligible()).isEqualTo(1);
        assertThat(external.d7Returned()).isEqualTo(1);
        assertThat(external.organicReturned()).isEqualTo(1);
        var friends = cohorts.stream().filter(c -> c.cohort().equals("friend")).findFirst().orElseThrow();
        assertThat(friends.activated()).isEqualTo(1);
        assertThat(friends.researchReaders()).isEqualTo(1);
        assertThat(friends.researchActivated()).isEqualTo(1);
        assertThat(friends.d7Eligible()).isZero();
        assertThat(friends.d7Retention()).isNull();
    }

    @Test
    void usesKoreanCalendarDaysAndSeparatesResearchFromOrganicReturns() {
        var participants = List.of(person("p", "external", "2026-10-01T14:50:00Z"));
        var events = List.of(event("p", "explainer_opened", "organic", "2026-10-01T14:50:00Z"),
                event("p", "source_opened", "organic", "2026-10-01T14:51:00Z"),
                event("p", "explainer_opened", "research", "2026-10-01T15:01:00Z"),
                event("p", "explainer_opened", "organic", "2026-10-08T14:52:00Z"));
        var external = BetaReport.calculate(participants, events, FROM, TO, NOW).get(1);
        assertThat(external.d7Returned()).isEqualTo(1);
        assertThat(external.researchReturned()).isEqualTo(1);
        assertThat(external.organicReturned()).isZero();
    }

    @Test
    void noActivationFromDepthWithoutPriorReadOrDifferentVisitKindOrOldRead() {
        var participants = List.of(person("p", "external", "2026-10-01T00:00:00Z"));
        var events = List.of(event("p", "source_opened", "organic", "2026-10-01T00:00:00Z"),
                event("p", "explainer_opened", "research", "2026-10-01T01:00:00Z"),
                event("p", "source_opened", "organic", "2026-10-01T01:01:00Z"),
                event("p", "source_opened", "research", "2026-10-01T02:00:00Z"));
        assertThat(BetaReport.calculate(participants, events, FROM, TO, NOW).get(1).activated()).isZero();
    }

    private static BetaReport.Participant person(String id, String cohort, String at) {
        return new BetaReport.Participant(id, cohort, Instant.parse(at));
    }
    private static BetaReport.Event event(String id, String kind, String visit, String at) {
        return new BetaReport.Event(id, kind, visit, Instant.parse(at));
    }
}
