package dev.parliament.tracking;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;

import org.springframework.http.HttpStatus;
import org.springframework.r2dbc.core.DatabaseClient;
import org.springframework.transaction.reactive.TransactionalOperator;
import org.springframework.web.server.ResponseStatusException;

import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.Instant;
import java.util.HexFormat;
import java.util.List;

public class TrackingRepository {
    public record ImportResult(String id, String version, String state, boolean replayed) {}

    public record Page(List<Activity> items, String nextCursor) {}

    public record History(
            String version, Instant reviewedAt, String correctionReason, boolean corrected) {}

    private final DatabaseClient db;
    private final TransactionalOperator tx;
    private final ObjectMapper mapper;
    private final TrackingPolicy policy = new TrackingPolicy();
    private final dev.parliament.knowledge.KnowledgeIdentity identities;
    public TrackingRepository(DatabaseClient db, TransactionalOperator tx, ObjectMapper mapper) {
        this(db,tx,mapper,new dev.parliament.knowledge.KnowledgeIdentity(db,false));
    }
    public TrackingRepository(DatabaseClient db, TransactionalOperator tx, ObjectMapper mapper,
            dev.parliament.knowledge.KnowledgeIdentity identities) {
        this.db = db;
        this.tx = tx;
        this.mapper = mapper;
        this.identities = identities;
    }

    public Mono<ImportResult> importDraft(Activity input) {
        return Mono.defer(
                () -> {
                    policy.validate(input);
                    Activity activity =
                            input.explained(input.summary(), false).visible(null, false);
                    String json = json(activity), hash = hash(json);
                    Mono<ImportResult> work =
                            db.sql("INSERT IGNORE INTO tracking_event(event_id) VALUES(:id)")
                                    .bind("id", activity.id())
                                    .fetch()
                                    .rowsUpdated()
                                    .then(
                                            db.sql(
                                                            "SELECT event_id FROM tracking_event"
                                                                + " WHERE event_id=:id FOR UPDATE")
                                                    .bind("id", activity.id())
                                                    .fetch()
                                                    .one())
                                    .then(
                                            db.sql(
                                                            "SELECT payload_hash,review_state FROM"
                                                                + " tracking_event_version WHERE"
                                                                + " event_id=:id AND"
                                                                + " version_id=:version")
                                                    .bind("id", activity.id())
                                                    .bind("version", activity.version())
                                                    .fetch()
                                                    .one())
                                    .flatMap(
                                            row ->
                                                    hash.equals(row.get("payload_hash"))
                                                            ? Mono.just(
                                                                    new ImportResult(
                                                                            activity.id(),
                                                                            activity.version(),
                                                                            String.valueOf(
                                                                                    row.get(
                                                                                            "review_state")),
                                                                            true))
                                                            : Mono.error(
                                                                    new ResponseStatusException(
                                                                            HttpStatus.CONFLICT,
                                                                            "immutable version"
                                                                                + " differs; use a"
                                                                                + " new version")))
                                    .switchIfEmpty(
                                            Mono.defer(
                                                    () ->
                                                            insert(activity, json, hash)
                                                                    .thenReturn(
                                                                            new ImportResult(
                                                                                    activity.id(),
                                                                                    activity
                                                                                            .version(),
                                                                                    "draft",
                                                                                    false))));
                    return tx.transactional(work);
                });
    }

    private Mono<Void> insert(Activity a, String json, String hash) {
        DatabaseClient.GenericExecuteSpec spec =
                db.sql(
                                """
                INSERT INTO tracking_event_version(event_id,version_id,payload_hash,activity,title,summary,activity_type,bill_id,published_at)
                VALUES(:id,:version,:hash,:activity,:title,:summary,:type,:bill,:published)
                """)
                        .bind("id", a.id())
                        .bind("version", a.version())
                        .bind("hash", hash)
                        .bind("activity", json)
                        .bind("title", a.title())
                        .bind("type", a.type())
                        .bind("published", a.publishedAt());
        spec = nullable(spec, "summary", a.summary());
        spec = nullable(spec, "bill", a.billId());
        return spec.fetch()
                .rowsUpdated()
                .thenMany(
                        Flux.fromIterable(a.personIds())
                                .distinct()
                                .concatMap(
                                        person ->
                                                db.sql(
                                                                "INSERT INTO"
                                                                    + " tracking_event_person(event_id,version_id,person_id)"
                                                                    + " VALUES(:id,:version,:person)")
                                                        .bind("id", a.id())
                                                        .bind("version", a.version())
                                                        .bind("person", person)
                                                        .fetch()
                                                        .rowsUpdated()))
                .thenMany(
                        Flux.fromIterable(a.topics())
                                .distinct()
                                .concatMap(
                                        topic ->
                                                db.sql(
                                                                "INSERT INTO"
                                                                    + " tracking_event_topic(event_id,version_id,topic)"
                                                                    + " VALUES(:id,:version,:topic)")
                                                        .bind("id", a.id())
                                                        .bind("version", a.version())
                                                        .bind("topic", topic)
                                                        .fetch()
                                                        .rowsUpdated()))
                .then();
    }

    public Mono<ImportResult> publish(String id, String version, String reviewer, String reason) {
        return checkedReview(id,version,null,Mono.defer(()->publishInternal(id,version,reviewer,reason)));
    }
    public Mono<ImportResult> publishFromKnowledge(String id,String version,String reviewer,String reason,String batchId) {
        TrackingPolicy.id(batchId);
        return checkedReview(id,version,batchId,Mono.defer(()->publishInternal(id,version,reviewer,reason)));
    }
    private <T> Mono<T> checkedReview(String id,String version,String batchId,Mono<T> action) {
        TrackingPolicy.id(id);TrackingPolicy.id(version);
        return tx.transactional(db.sql("SELECT event_id FROM tracking_event WHERE event_id=:id FOR UPDATE")
                .bind("id",id).fetch().one().switchIfEmpty(Mono.error(notFound()))
                .then(knowledgeReviewGuard(id,version,batchId))
                .then(action));
    }
    private Mono<Void> knowledgeReviewGuard(String id,String version,String batchId) {
        if(batchId==null&&!identities.hasStorage())return Mono.empty();
        var q=db.sql("SELECT batch_id FROM knowledge_context WHERE event_id=:id AND event_version=:version").bind("id",id).bind("version",version).map((r,m)->r.get("batch_id",String.class)).one();
        if(batchId!=null)return q.filter(batchId::equals).switchIfEmpty(Mono.error(new org.springframework.web.server.ResponseStatusException(org.springframework.http.HttpStatus.CONFLICT,"knowledge batch context mismatch"))).then();
        return q.flatMap(found->Mono.<Void>error(new org.springframework.web.server.ResponseStatusException(org.springframework.http.HttpStatus.CONFLICT,"knowledge batch review required"))).then();
    }
    private Mono<ImportResult> publishInternal(String id, String version, String reviewer, String reason) {
        TrackingPolicy.id(id);
        TrackingPolicy.id(version);
        TrackingPolicy.text(reviewer, 100, "reviewer");
        if (reason != null && reason.length() > 1000)
            throw new IllegalArgumentException("correction reason too long");
        Mono<ImportResult> work =
                db.sql("SELECT latest_version FROM tracking_event WHERE event_id=:id FOR UPDATE")
                        .bind("id", id)
                        .fetch()
                        .one()
                        .switchIfEmpty(Mono.error(notFound()))
                        .flatMap(
                                event ->
                                        db.sql(
                                                        "SELECT activity,review_state FROM"
                                                                + " tracking_event_version WHERE"
                                                                + " event_id=:id AND"
                                                                + " version_id=:version")
                                                .bind("id", id)
                                                .bind("version", version)
                                                .fetch()
                                                .one()
                                                .switchIfEmpty(Mono.error(notFound()))
                                                .flatMap(
                                                        row -> {
                                                            Activity a =
                                                                    parse(
                                                                            String.valueOf(
                                                                                    row.get(
                                                                                            "activity")));
                                                            policy.validate(a);
                                                            String latest =
                                                                    (String)
                                                                            event.get(
                                                                                    "latest_version");
                                                            if ("published"
                                                                    .equals(
                                                                            row.get(
                                                                                    "review_state"))) {
                                                                return Mono.just(
                                                                        new ImportResult(
                                                                                id,
                                                                                version,
                                                                                "published",
                                                                                true));
                                                            }
                                                            if (!"draft"
                                                                    .equals(
                                                                            row.get(
                                                                                    "review_state")))
                                                                return Mono.error(
                                                                        new ResponseStatusException(
                                                                                HttpStatus.CONFLICT,
                                                                                "rejected"
                                                                                    + " version"));
                                                            boolean corrected =
                                                                    latest != null
                                                                            && !latest.equals(
                                                                                    version);
                                                            if (corrected
                                                                    && (reason == null
                                                                            || reason.isBlank()))
                                                                return Mono.error(
                                                                        new IllegalArgumentException(
                                                                                "correction reason"
                                                                                    + " required"));
                                                            return reserveReviewBudget(a)
                                                                    .then(
                                                                            db.sql(
                                                                                            """
                                    UPDATE tracking_event_version SET review_state='published',reviewed_by=:reviewer,reviewed_at=:at,correction_reason=:reason,corrected=:corrected
                                    WHERE event_id=:id AND version_id=:version AND review_state='draft'
                                    """)
                                                                                    .bind(
                                                                                            "reviewer",
                                                                                            reviewer)
                                                                                    .bind(
                                                                                            "at",
                                                                                            Instant
                                                                                                    .now())
                                                                                    .bind(
                                                                                            "reason",
                                                                                            reason
                                                                                                            == null
                                                                                                    ? ""
                                                                                                    : reason)
                                                                                    .bind(
                                                                                            "corrected",
                                                                                            corrected)
                                                                                    .bind("id", id)
                                                                                    .bind(
                                                                                            "version",
                                                                                            version)
                                                                                    .fetch()
                                                                                    .rowsUpdated())
                                                                    .then(
                                                                            db.sql(
                                                                                            "UPDATE"
                                                                                                + " tracking_event"
                                                                                                + " SET latest_version=:version"
                                                                                                + " WHERE"
                                                                                                + " event_id=:id")
                                                                                    .bind("id", id)
                                                                                    .bind(
                                                                                            "version",
                                                                                            version)
                                                                                    .fetch()
                                                                                    .rowsUpdated())
                                                                    .thenReturn(
                                                                            new ImportResult(
                                                                                    id,
                                                                                    version,
                                                                                    "published",
                                                                                    false));
                                                        }));
        return tx.transactional(work);
    }

    private Mono<Void> reserveReviewBudget(Activity activity) {
        if (activity.summary() == null) return Mono.empty();
        String day = java.time.LocalDate.now(java.time.ZoneId.of("Asia/Seoul")).toString();
        return db.sql(
                        "INSERT IGNORE INTO tracking_review_budget(review_day,review_count)"
                                + " VALUES(:day,0)")
                .bind("day", day)
                .fetch()
                .rowsUpdated()
                .then(
                        db.sql(
                                        "UPDATE tracking_review_budget SET"
                                            + " review_count=review_count+1 WHERE review_day=:day"
                                            + " AND review_count<3")
                                .bind("day", day)
                                .fetch()
                                .rowsUpdated())
                .flatMap(
                        count ->
                                count == 1
                                        ? Mono.empty()
                                        : Mono.error(
                                                new ResponseStatusException(
                                                        HttpStatus.TOO_MANY_REQUESTS,
                                                        "daily detailed explanation review budget"
                                                                + " reached")));
    }

    public Mono<Void> reject(String id, String version) {
        return checkedReview(id,version,null,Mono.defer(()->rejectInternal(id,version)));
    }
    public Mono<Void> rejectFromKnowledge(String id,String version,String batchId) {
        TrackingPolicy.id(batchId);return checkedReview(id,version,batchId,Mono.defer(()->rejectInternal(id,version)));
    }
    private Mono<Void> rejectInternal(String id,String version) {
        TrackingPolicy.id(id);
        TrackingPolicy.id(version);
        return db.sql(
                        "UPDATE tracking_event_version SET review_state='rejected' WHERE"
                                + " event_id=:id AND version_id=:version AND review_state='draft'")
                .bind("id", id)
                .bind("version", version)
                .fetch()
                .rowsUpdated()
                .flatMap(count -> count == 1 ? Mono.empty() : Mono.error(notFound()));
    }

    public Flux<Activity> drafts() {
        return db.sql(
                        "SELECT activity FROM tracking_event_version WHERE review_state='draft'"
                                + " ORDER BY published_at DESC LIMIT 100")
                .map((row, meta) -> parse(row.get("activity", String.class)))
                .all();
    }

    public Flux<History> history(String id) {
        TrackingPolicy.id(id);
        return db.sql(
                        "SELECT version_id,reviewed_at,correction_reason,corrected FROM"
                            + " tracking_event_version v WHERE event_id=:id AND"
                            + " review_state='published'" + knowledgePublication() + " ORDER BY reviewed_at DESC,version_id DESC"
                            + " LIMIT 100")
                .bind("id", id)
                .map(
                        (row, meta) ->
                                new History(
                                        row.get("version_id", String.class),
                                        row.get("reviewed_at", Instant.class),
                                        row.get("correction_reason", String.class),
                                        Boolean.TRUE.equals(row.get("corrected", Boolean.class))))
                .all();
    }

    public Mono<Activity> detail(String id, String version) {
        TrackingPolicy.id(id);
        String join =
                version == null
                        ? " AND v.version_id=e.latest_version"
                        : " AND v.version_id=:version";
        var spec =
                db.sql(
                                "SELECT v.activity,v.corrected,v.reviewed_at FROM"
                                        + " tracking_event_version v JOIN tracking_event e ON"
                                        + " e.event_id=v.event_id WHERE v.event_id=:id AND"
                                        + " v.review_state='published'"
                                        + join + knowledgePublication())
                        .bind("id", id);
        if (version != null) spec = spec.bind("version", TrackingPolicy.id(version));
        return spec.map(
                        (row, meta) ->
                                effective(
                                        row.get("activity", String.class),
                                        Boolean.TRUE.equals(row.get("corrected", Boolean.class)),
                                        row.get("reviewed_at", Instant.class)))
                .one()
                .switchIfEmpty(Mono.error(notFound()));
    }

    public Mono<Page> feed(
            String person,
            String topic,
            String bill,
            String type,
            String query,
            TrackingCursor cursor,
            int limit) {
        if (limit < 1 || limit > 100) throw new IllegalArgumentException("limit must be 1..100");
        StringBuilder sql =
                new StringBuilder(
                        "SELECT v.activity,v.corrected,v.reviewed_at FROM tracking_event e JOIN"
                            + " tracking_event_version v ON v.event_id=e.event_id AND"
                            + " v.version_id=e.latest_version WHERE v.review_state='published'");
        sql.append(knowledgePublication());
        if (person != null)
            sql.append(
                    " AND EXISTS(SELECT 1 FROM tracking_event_person p WHERE p.event_id=v.event_id"
                            + " AND p.version_id=v.version_id AND " + identities.matches("p.person_id",":person") + ")");
        if (topic != null)
            sql.append(
                    " AND EXISTS(SELECT 1 FROM tracking_event_topic t WHERE t.event_id=v.event_id"
                            + " AND t.version_id=v.version_id AND t.topic=:topic)");
        if (bill != null) sql.append(" AND v.bill_id=:bill");
        if (type != null) sql.append(" AND v.activity_type=:type");
        if (query != null)
            sql.append(" AND MATCH(v.title,v.summary) AGAINST(:query IN NATURAL LANGUAGE MODE)");
        if (cursor != null)
            sql.append(
                    " AND (v.reviewed_at < :at OR (v.reviewed_at=:at AND v.event_id<:cursorId))");
        sql.append(" ORDER BY v.reviewed_at DESC,v.event_id DESC LIMIT :limit");
        var spec = db.sql(sql.toString()).bind("limit", limit + 1);
        if (person != null) spec = spec.bind("person", TrackingPolicy.id(person));
        if (topic != null) spec = spec.bind("topic", TrackingPolicy.id(topic));
        if (bill != null) spec = spec.bind("bill", TrackingPolicy.id(bill));
        if (type != null) spec = spec.bind("type", TrackingPolicy.id(type));
        if (query != null) {
            TrackingPolicy.text(query, 200, "query");
            spec = spec.bind("query", query);
        }
        if (cursor != null)
            spec = spec.bind("at", cursor.publishedAt()).bind("cursorId", cursor.id());
        return spec.map(
                        (row, meta) ->
                                effective(
                                        row.get("activity", String.class),
                                        Boolean.TRUE.equals(row.get("corrected", Boolean.class)),
                                        row.get("reviewed_at", Instant.class)))
                .all()
                .collectList()
                .map(
                        items -> {
                            boolean more = items.size() > limit;
                            List<Activity> page = more ? items.subList(0, limit) : items;
                            Activity last = page.isEmpty() ? null : page.get(page.size() - 1);
                            return new Page(
                                    page,
                                    more
                                            ? new TrackingCursor(last.changedAt(), last.id())
                                                    .encode()
                                            : null);
                        });
    }

    private Activity effective(String value, boolean corrected, Instant changedAt) {
        Activity a = parse(value);
        return a.explained(a.summary(), corrected).visible(changedAt, corrected);
    }

    String knowledgePublication() {
        return identities.hasStorage()?" AND (NOT EXISTS(SELECT 1 FROM knowledge_context kc WHERE kc.event_id=v.event_id AND kc.event_version=v.version_id) OR EXISTS(SELECT 1 FROM knowledge_context kc JOIN knowledge_batch kb ON kb.batch_id=kc.batch_id WHERE kc.event_id=v.event_id AND kc.event_version=v.version_id AND kb.review_state='published'))":"";
    }

    Activity parse(String value) {
        try {
            return mapper.readValue(value, Activity.class);
        } catch (JsonProcessingException ex) {
            throw new IllegalStateException("stored activity invalid", ex);
        }
    }

    String json(Object value) {
        try {
            return mapper.writeValueAsString(value);
        } catch (JsonProcessingException ex) {
            throw new IllegalArgumentException("invalid activity", ex);
        }
    }

    static String hash(String value) {
        try {
            return HexFormat.of()
                    .formatHex(
                            MessageDigest.getInstance("SHA-256")
                                    .digest(value.getBytes(StandardCharsets.UTF_8)));
        } catch (java.security.NoSuchAlgorithmException ex) {
            throw new IllegalStateException(ex);
        }
    }

    private static DatabaseClient.GenericExecuteSpec nullable(
            DatabaseClient.GenericExecuteSpec spec, String key, String value) {
        return value == null ? spec.bindNull(key, String.class) : spec.bind(key, value);
    }

    static ResponseStatusException notFound() {
        return new ResponseStatusException(HttpStatus.NOT_FOUND, "record unavailable");
    }
}
