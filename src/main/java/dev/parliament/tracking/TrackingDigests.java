package dev.parliament.tracking;

import org.springframework.r2dbc.core.DatabaseClient;
import org.springframework.transaction.reactive.TransactionalOperator;

import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;

import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;

/** Opt-in, version-deduplicated mail spool. Delivery is a separate explicit operation. */
public final class TrackingDigests {
    public record BuildRequest(String frequency, Instant from, Instant to) {}

    public record Result(int queued, String status) {}

    private record Recipient(String email, String unsubscribeToken) {}

    private final DatabaseClient db;
    private final TrackingRepository events;
    private final TrackingAuthRepository auth;
    private final TrackingAuthPolicy policy;
    private final TransactionalOperator tx;
    private final dev.parliament.knowledge.KnowledgeIdentity identities;

    public TrackingDigests(
            DatabaseClient db,
            TrackingRepository events,
            TrackingAuthRepository auth,
            TrackingAuthPolicy policy,
            TransactionalOperator tx) {
        this(db,events,auth,policy,tx,new dev.parliament.knowledge.KnowledgeIdentity(db,false));
    }
    public TrackingDigests(DatabaseClient db,TrackingRepository events,TrackingAuthRepository auth,TrackingAuthPolicy policy,
            TransactionalOperator tx,dev.parliament.knowledge.KnowledgeIdentity identities) {
        this.db = db;
        this.events = events;
        this.auth = auth;
        this.policy = policy;
        this.tx = tx;
        this.identities = identities;
    }

    public Mono<Result> build(String frequency, Instant from, Instant to) {
        TrackingPolicy.require(
                List.of("daily", "weekly").contains(frequency), "digest frequency required");
        TrackingPolicy.require(
                from != null && to != null && from.isBefore(to),
                "valid digest time window required");
        AtomicInteger queued = new AtomicInteger();
        return db.sql(
                        "SELECT user_id FROM tracking_user WHERE email_enabled=true AND verified_at"
                            + " IS NOT NULL AND frequency=:frequency ORDER BY user_id LIMIT 100")
                .bind("frequency", frequency)
                .map((row, meta) -> row.get("user_id", String.class))
                .all()
                .concatMap(
                        user ->
                                tx.transactional(buildFor(user, frequency, from, to))
                                        .doOnNext(count -> queued.addAndGet(count)))
                .then(
                        Mono.fromSupplier(
                                () ->
                                        new Result(
                                                queued.get(),
                                                "queued; delivery requires an explicit mail"
                                                        + " sender")));
    }

    private Mono<Integer> buildFor(String user, String frequency, Instant from, Instant to) {
        return db.sql(
                        "SELECT email,unsubscribe_token FROM tracking_user WHERE user_id=:user AND"
                                + " email_enabled=true AND verified_at IS NOT NULL AND"
                                + " frequency=:frequency FOR UPDATE")
                .bind("user", user)
                .bind("frequency", frequency)
                .map(
                        (row, meta) ->
                                new Recipient(
                                        row.get("email", String.class),
                                        row.get("unsubscribe_token", String.class)))
                .one()
                .flatMap(
                        recipient ->
                                matchingActivities(user, from, to)
                                        .flatMap(items -> spool(user, frequency, recipient, items)))
                .defaultIfEmpty(0);
    }

    private Mono<List<Activity>> matchingActivities(String user, Instant from, Instant to) {
        return db.sql(
                        ("""
                SELECT v.activity,v.corrected,v.reviewed_at FROM tracking_event e JOIN tracking_event_version v ON v.event_id=e.event_id AND v.version_id=e.latest_version
                WHERE v.review_state='published' AND v.reviewed_at>=:from AND v.reviewed_at<:to
                  AND NOT EXISTS(SELECT 1 FROM tracking_digest_item d WHERE d.user_id=:user AND d.event_id=v.event_id AND d.version_id=v.version_id)
                  AND EXISTS(SELECT 1 FROM tracking_follow f WHERE f.user_id=:user AND (
                    (f.target_kind='bill' AND f.target_id=v.bill_id)
                    OR (f.target_kind='person' AND EXISTS(SELECT 1 FROM tracking_event_person p WHERE p.event_id=v.event_id AND p.version_id=v.version_id AND $PERSON_MATCH))
                    OR (f.target_kind IN ('topic','issue') AND EXISTS(SELECT 1 FROM tracking_event_topic t WHERE t.event_id=v.event_id AND t.version_id=v.version_id AND t.topic=f.target_id))))
                $KNOWLEDGE_GATE ORDER BY v.reviewed_at DESC,v.event_id DESC LIMIT 100
                """).replace("$PERSON_MATCH",identities.matches("p.person_id","f.target_id")).replace("$KNOWLEDGE_GATE",identities.hasStorage()?" AND (NOT EXISTS(SELECT 1 FROM knowledge_context kc WHERE kc.event_id=v.event_id AND kc.event_version=v.version_id) OR EXISTS(SELECT 1 FROM knowledge_context kc JOIN knowledge_batch kb ON kb.batch_id=kc.batch_id WHERE kc.event_id=v.event_id AND kc.event_version=v.version_id AND kb.review_state='published' AND kc.change_kind NOT IN ('explanation_only','extraction_only')))":""))
                .bind("from", from)
                .bind("to", to)
                .bind("user", user)
                .map(
                        (row, meta) ->
                                events.parse(row.get("activity", String.class))
                                        .visible(
                                                row.get("reviewed_at", Instant.class),
                                                Boolean.TRUE.equals(
                                                        row.get("corrected", Boolean.class))))
                .all()
                .collectList();
    }

    private Mono<Integer> spool(
            String user, String frequency, Recipient recipient, List<Activity> items) {
        if (items.isEmpty()) return Mono.just(0);
        String dedupe =
                TrackingRepository.hash(
                        "digest:"
                                + user
                                + ":"
                                + items.stream()
                                        .map(a -> a.id() + ":" + a.version())
                                        .sorted()
                                        .toList());
        List<Map<String, Object>> cards =
                items.stream()
                        .map(
                                a ->
                                        Map.<String, Object>of(
                                                "id",
                                                a.id(),
                                                "version",
                                                a.version(),
                                                "title",
                                                a.title(),
                                                "corrected",
                                                a.corrected(),
                                                "url",
                                                policy.baseUrl()
                                                        + "/activities/"
                                                        + a.id()
                                                        + "?version="
                                                        + a.version()))
                        .toList();
        return auth.queue(
                        user,
                        "digest",
                        dedupe,
                        Map.of(
                                "email",
                                recipient.email(),
                                "frequency",
                                frequency,
                                "activities",
                                cards,
                                "unsubscribeUrl",
                                policy.baseUrl()
                                        + "/unsubscribe?token="
                                        + recipient.unsubscribeToken(),
                                "coverage",
                                "최근 100개의 검수된 공개 활동"))
                .thenMany(
                        Flux.fromIterable(items)
                                .concatMap(
                                        a ->
                                                db.sql(
                                                                "INSERT IGNORE INTO"
                                                                    + " tracking_digest_item(user_id,event_id,version_id)"
                                                                    + " VALUES(:user,:event,:version)")
                                                        .bind("user", user)
                                                        .bind("event", a.id())
                                                        .bind("version", a.version())
                                                        .fetch()
                                                        .rowsUpdated()))
                .then(Mono.just(1));
    }
}
