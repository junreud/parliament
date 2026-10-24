package dev.parliament.beta;

import java.time.Duration;
import java.time.Instant;
import java.time.ZoneId;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

/** Cohorts are enrollment-period cohorts; calendar-day comparisons use Korea time. */
public final class BetaReport {
    private static final ZoneId ZONE = ZoneId.of("Asia/Seoul");
    public record Participant(String id, String cohort, Instant enrolledAt) {}
    public record Event(String participantId, String event, String visitKind, Instant at) {}
    private record Activation(Instant at, String visitKind) {}
    public record Cohort(String cohort, long enrolled, long activated, long organicReaders, long researchReaders,
                         long organicActivated, long researchActivated, long d7Eligible,
                         long d7Returned, long organicReturned, long researchReturned,
                         Double d7Retention) {}
    public record Report(Instant observedAt, String calendarZone, int retentionDays,
                         List<Cohort> cohorts, Map<String, Long> acquisition) {}

    private BetaReport() {}

    public static List<Cohort> calculate(List<Participant> participants, List<Event> events,
                                         Instant from, Instant to, Instant now) {
        Map<String, List<Event>> byParticipant = events.stream().filter(e -> !e.at().isAfter(now))
                .sorted(Comparator.comparing(Event::at)).collect(Collectors.groupingBy(Event::participantId));
        List<Cohort> result = new ArrayList<>();
        for (String kind : List.of("friend", "external")) {
            long enrolled = 0, activated = 0, eligible = 0, returned = 0, organic = 0, research = 0;
            long organicReaders = 0, researchReaders = 0, organicActivated = 0, researchActivated = 0;
            for (Participant participant : participants) {
                if (!participant.cohort().equals(kind) || participant.enrolledAt().isBefore(from)
                        || !participant.enrolledAt().isBefore(to) || participant.enrolledAt().isAfter(now)) continue;
                enrolled++;
                List<Event> reads = byParticipant.getOrDefault(participant.id(), List.of());
                if (reads.stream().anyMatch(e -> e.event().equals("explainer_opened") && e.visitKind().equals("organic"))) organicReaders++;
                if (reads.stream().anyMatch(e -> e.event().equals("explainer_opened") && e.visitKind().equals("research"))) researchReaders++;
                Activation first = activation(reads);
                if (first == null) continue;
                activated++;
                if (first.visitKind().equals("organic")) organicActivated++;
                else researchActivated++;
                Instant activation = first.at();
                Instant end = activation.plus(Duration.ofDays(7));
                if (end.isAfter(now)) continue;
                eligible++;
                boolean organicReturn = false, researchReturn = false;
                for (Event event : reads) {
                    if (!event.event().equals("explainer_opened") || !event.at().isBefore(end)
                            || !event.at().isAfter(activation)
                            || event.at().atZone(ZONE).toLocalDate().equals(activation.atZone(ZONE).toLocalDate())) continue;
                    if (event.visitKind().equals("organic")) organicReturn = true;
                    else researchReturn = true;
                }
                if (organicReturn || researchReturn) returned++;
                if (organicReturn) organic++;
                if (researchReturn) research++;
            }
            result.add(new Cohort(kind, enrolled, activated, organicReaders, researchReaders, organicActivated, researchActivated,
                    eligible, returned, organic, research,
                    eligible == 0 ? null : (double) returned / eligible));
        }
        return result;
    }

    private static Activation activation(List<Event> events) {
        Map<String, Instant> lastRead = new java.util.HashMap<>();
        for (Event event : events) {
            if (event.event().equals("explainer_opened")) lastRead.put(event.visitKind(), event.at());
            else {
                Instant read = lastRead.get(event.visitKind());
                if (read != null && !read.isBefore(event.at().minus(Duration.ofMinutes(30)))) return new Activation(event.at(), event.visitKind());
            }
        }
        return null;
    }
}
