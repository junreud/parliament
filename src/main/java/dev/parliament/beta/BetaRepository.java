package dev.parliament.beta;

import java.time.Instant;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.ZoneOffset;
import java.util.Map;
import java.util.UUID;
import java.util.stream.Collectors;
import org.springframework.http.HttpStatus;
import org.springframework.r2dbc.core.DatabaseClient;
import org.springframework.transaction.reactive.TransactionalOperator;
import org.springframework.web.server.ResponseStatusException;
import reactor.core.publisher.Mono;

/** Beta contacts and pseudonymous behavior are separate tables with a bounded consent lifetime. */
public class BetaRepository {
    public record Session(String participantId, String csrfToken, Instant expiresAt) {}
    public record Enrolled(String token, String csrfToken) {}
    private final DatabaseClient db;
    private final TransactionalOperator transaction;
    private final BetaPolicy policy;

    public BetaRepository(DatabaseClient db, TransactionalOperator transaction, BetaPolicy policy) {
        this.db = db;
        this.transaction = transaction;
        this.policy = policy;
    }

    public Mono<Enrolled> enroll(BetaPolicy.Enrollment input, Instant now) {
        String id = UUID.randomUUID().toString(), token = policy.token(), csrf = policy.token();
        Instant expires = now.plus(BetaPolicy.RETENTION);
        Mono<Enrolled> writes = db.sql("""
                INSERT INTO beta_participant(participant_id, cohort, source, consent_version,
                    enrolled_at, expires_at, session_hash, csrf_token)
                VALUES(:id,:cohort,:source,:version,:at,:expires,:session,:csrf)
                """).bind("id", id).bind("cohort", input.cohort()).bind("source", input.source())
                .bind("version", BetaPolicy.CONSENT_VERSION).bind("at", now).bind("expires", expires)
                .bind("session", policy.hash(token)).bind("csrf", csrf).fetch().rowsUpdated()
                .then(db.sql("INSERT INTO beta_contact(participant_id,email) VALUES(:id,:email)")
                        .bind("id", id).bind("email", input.email()).fetch().rowsUpdated())
                .thenReturn(new Enrolled(token, csrf));
        return unavailable(transaction.transactional(writes));
    }

    public Mono<Session> current(String token, Instant now) {
        if (!policy.validToken(token)) return Mono.empty();
        return unavailable(db.sql("""
                SELECT participant_id,csrf_token,expires_at FROM beta_participant
                WHERE session_hash=:hash AND expires_at>:now
                """).bind("hash", policy.hash(token)).bind("now", now)
                .map((row, meta) -> new Session(row.get("participant_id", String.class),
                        row.get("csrf_token", String.class), instant(row.get("expires_at")))).one());
    }

    public Mono<Void> record(Session session, BetaPolicy.Event event, Instant now) {
        long bucket = now.getEpochSecond() / 300;
        // Unique five-minute buckets suppress repeated browser rendering and concurrent retries.
        return unavailable(db.sql("""
                INSERT INTO beta_event(participant_id,event_kind,visit_kind,bucket,occurred_at)
                SELECT :id,:event,:visit,:bucket,:at FROM beta_participant
                WHERE participant_id=:id AND expires_at>:at
                ON DUPLICATE KEY UPDATE bucket=bucket
                """).bind("id", session.participantId()).bind("event", event.event())
                .bind("visit", event.visitKind()).bind("bucket", bucket).bind("at", now)
                .fetch().rowsUpdated().then());
    }

    public Mono<Void> acquisition(String source, Instant now) {
        LocalDate day = now.atZone(java.time.ZoneId.of("Asia/Seoul")).toLocalDate();
        return unavailable(db.sql("""
                INSERT INTO beta_acquisition(day,source,visits) VALUES(:day,:source,1)
                ON DUPLICATE KEY UPDATE visits=visits+1
                """).bind("day", day).bind("source", source).fetch().rowsUpdated().then());
    }

    public Mono<Void> withdraw(String participantId) {
        // FK cascades atomically erase the separate contact and all pseudonymous event rows.
        return unavailable(db.sql("DELETE FROM beta_participant WHERE participant_id=:id")
                .bind("id", participantId).fetch().rowsUpdated().then());
    }

    public Mono<Void> purge(Instant now) {
        return unavailable(new BetaRetention(db).purge(now));
    }

    /** Both bounds must be exact Asia/Seoul midnight so cohort and aggregate windows match. */
    public Mono<BetaReport.Report> report(Instant from, Instant to, Instant now) {
        if (from == null || to == null || !from.isBefore(to)
                || !koreanMidnight(from) || !koreanMidnight(to)
                || java.time.Duration.between(from, to).compareTo(BetaPolicy.RETENTION) > 0)
            return Mono.error(new IllegalArgumentException("beta report requires Korea-midnight bounds and at most 35 days"));
        var participants = db.sql("""
                SELECT participant_id,cohort,enrolled_at FROM beta_participant
                WHERE enrolled_at>=:from AND enrolled_at<:to AND expires_at>:now
                """).bind("from", from).bind("to", to).bind("now", now)
                .map((row, meta) -> new BetaReport.Participant(row.get("participant_id", String.class),
                        row.get("cohort", String.class), instant(row.get("enrolled_at")))).all().collectList();
        var events = db.sql("""
                SELECT e.participant_id,e.event_kind,e.visit_kind,e.occurred_at
                FROM beta_event e JOIN beta_participant p ON p.participant_id=e.participant_id
                WHERE p.enrolled_at>=:from AND p.enrolled_at<:to AND p.expires_at>:now AND e.occurred_at<=:now
                """).bind("from", from).bind("to", to).bind("now", now)
                .map((row, meta) -> new BetaReport.Event(row.get("participant_id", String.class),
                        row.get("event_kind", String.class), row.get("visit_kind", String.class),
                        instant(row.get("occurred_at")))).all().collectList();
        var acquisition = db.sql("""
                SELECT source,COALESCE(SUM(visits),0) AS visits FROM beta_acquisition
                WHERE day>=:fromDay AND day<:toDay GROUP BY source
                """).bind("fromDay", from.atZone(java.time.ZoneId.of("Asia/Seoul")).toLocalDate())
                .bind("toDay", to.atZone(java.time.ZoneId.of("Asia/Seoul")).toLocalDate())
                .map((row, meta) -> Map.entry(row.get("source", String.class), ((Number)row.get("visits")).longValue()))
                .all().collect(Collectors.toMap(Map.Entry::getKey, Map.Entry::getValue));
        return unavailable(Mono.zip(participants, events, acquisition).map(values ->
                new BetaReport.Report(now, "Asia/Seoul", 35,
                        BetaReport.calculate(values.getT1(), values.getT2(), from, to, now), values.getT3())));
    }

    private static boolean koreanMidnight(Instant value) {
        return value.atZone(java.time.ZoneId.of("Asia/Seoul")).toLocalTime().equals(java.time.LocalTime.MIDNIGHT);
    }

    private static Instant instant(Object value) {
        if (value instanceof Instant at) return at;
        if (value instanceof java.time.ZonedDateTime at) return at.toInstant();
        if (value instanceof java.time.OffsetDateTime at) return at.toInstant();
        if (value instanceof LocalDateTime at) return at.toInstant(ZoneOffset.UTC);
        throw new IllegalStateException("unexpected database timestamp");
    }
    private static <T> Mono<T> unavailable(Mono<T> operation) {
        return operation.onErrorMap(error -> !(error instanceof IllegalArgumentException)
                        && !(error instanceof ResponseStatusException),
                error -> new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "beta unavailable"));
    }
}
