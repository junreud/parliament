package dev.parliament.tracking;

import com.fasterxml.jackson.databind.ObjectMapper;

import org.springframework.http.HttpStatus;
import org.springframework.r2dbc.core.DatabaseClient;
import org.springframework.transaction.reactive.TransactionalOperator;
import org.springframework.web.server.ResponseStatusException;

import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.UUID;

/** Hashed token storage and mail queue only; this class never sends email. */
public final class TrackingAuthRepository {
    public record Follow(String kind, String targetId) {}

    public record Session(String token, String userId, String csrfToken, String frequency) {}

    public record Me(
            boolean authenticated, String csrfToken, List<Follow> follows, String frequency) {}

    private final DatabaseClient db;
    private final TrackingRepository events;
    private final TransactionalOperator tx;
    private final ObjectMapper mapper;
    private final TrackingAuthPolicy policy;
    private final Clock clock;
    private final TrackingIssues issues;
    private final dev.parliament.knowledge.KnowledgeIdentity identities;

    public TrackingAuthRepository(
            DatabaseClient db,
            TrackingRepository events,
            ObjectMapper mapper,
            TrackingAuthPolicy policy,
            Clock clock,
            TrackingIssues issues,
            TransactionalOperator tx) {
        this(db,events,mapper,policy,clock,issues,tx,new dev.parliament.knowledge.KnowledgeIdentity(db,false));
    }
    public TrackingAuthRepository(DatabaseClient db,TrackingRepository events,ObjectMapper mapper,TrackingAuthPolicy policy,Clock clock,
            TrackingIssues issues,TransactionalOperator tx,dev.parliament.knowledge.KnowledgeIdentity identities) {
        this.db = db;
        this.events = events;
        this.mapper = mapper;
        this.policy = policy;
        this.clock = clock;
        this.issues = issues;
        this.tx = tx;
        this.identities = identities;
    }

    public Mono<Void> requestLink(String input, String client) {
        String email = TrackingAuthPolicy.email(input);
        String token = TrackingAuthPolicy.token();
        Instant now = clock.instant(), expires = now.plus(Duration.ofMinutes(15));
        String candidate = UUID.randomUUID().toString();
        String unsubscribe = TrackingAuthPolicy.token();
        Mono<Void> work =
                rate("email:" + email, 5)
                        .zipWith(rate("client:" + client, 60))
                        .flatMap(
                                allowed -> {
                                    if (!allowed.getT1() || !allowed.getT2()) return Mono.empty();
                                    return db.sql(
                                                    "INSERT IGNORE INTO"
                                                        + " tracking_user(user_id,email,unsubscribe_hash,unsubscribe_token)"
                                                        + " VALUES(:id,:email,:unsubscribe,:unsubscribeToken)")
                                            .bind("id", candidate)
                                            .bind("email", email)
                                            .bind(
                                                    "unsubscribe",
                                                    TrackingRepository.hash(unsubscribe))
                                            .bind("unsubscribeToken", unsubscribe)
                                            .fetch()
                                            .rowsUpdated()
                                            .then(
                                                    db.sql(
                                                                    "SELECT user_id FROM"
                                                                            + " tracking_user WHERE"
                                                                            + " email=:email")
                                                            .bind("email", email)
                                                            .map(
                                                                    (row, meta) ->
                                                                            row.get(
                                                                                    "user_id",
                                                                                    String.class))
                                                            .one())
                                            .flatMap(
                                                    user ->
                                                            db.sql(
                                                                            "INSERT INTO"
                                                                                + " tracking_login_token(token_hash,user_id,expires_at)"
                                                                                + " VALUES(:hash,:user,:expires)")
                                                                    .bind(
                                                                            "hash",
                                                                            TrackingRepository.hash(
                                                                                    token))
                                                                    .bind("user", user)
                                                                    .bind("expires", expires)
                                                                    .fetch()
                                                                    .rowsUpdated()
                                                                    .then(
                                                                            queue(
                                                                                    user,
                                                                                    "login",
                                                                                    TrackingRepository
                                                                                            .hash(
                                                                                                    "login:"
                                                                                                            + token),
                                                                                    Map.of(
                                                                                            "email",
                                                                                            email,
                                                                                            "loginUrl",
                                                                                            policy
                                                                                                            .baseUrl()
                                                                                                    + "/auth/verify?token="
                                                                                                    + token,
                                                                                            "expiresAt",
                                                                                            expires
                                                                                                    .toString()))));
                                });
        return tx.transactional(work)
                .then(
                        db.sql("DELETE FROM tracking_auth_rate WHERE hour_bucket < :bucket")
                                .bind("bucket", now.getEpochSecond() / 3600 - 48)
                                .fetch()
                                .rowsUpdated())
                .then();
    }

    private Mono<Boolean> rate(String key, int maximum) {
        String hash = TrackingRepository.hash(key);
        long bucket = clock.instant().getEpochSecond() / 3600;
        return db.sql(
                        "INSERT INTO tracking_auth_rate(rate_key,hour_bucket,attempts)"
                            + " VALUES(:key,:bucket,1) ON DUPLICATE KEY UPDATE attempts=attempts+1")
                .bind("key", hash)
                .bind("bucket", bucket)
                .fetch()
                .rowsUpdated()
                .then(
                        db.sql(
                                        "SELECT attempts FROM tracking_auth_rate WHERE"
                                                + " rate_key=:key AND hour_bucket=:bucket")
                                .bind("key", hash)
                                .bind("bucket", bucket)
                                .map((row, meta) -> row.get("attempts", Integer.class) <= maximum)
                                .one());
    }

    public Mono<Session> verify(String token) {
        TrackingAuthPolicy.tokenFormat(token);
        String hash = TrackingRepository.hash(token);
        String session = TrackingAuthPolicy.token(), csrf = TrackingAuthPolicy.token();
        Instant now = clock.instant();
        Mono<Session> work =
                db.sql(
                                "UPDATE tracking_login_token SET consumed_at=:now WHERE"
                                        + " token_hash=:hash AND consumed_at IS NULL AND"
                                        + " expires_at>:now")
                        .bind("hash", hash)
                        .bind("now", now)
                        .fetch()
                        .rowsUpdated()
                        .flatMap(
                                count ->
                                        count == 1
                                                ? db.sql(
                                                                "SELECT user_id FROM"
                                                                    + " tracking_login_token WHERE"
                                                                    + " token_hash=:hash")
                                                        .bind("hash", hash)
                                                        .map(
                                                                (row, meta) ->
                                                                        row.get(
                                                                                "user_id",
                                                                                String.class))
                                                        .one()
                                                : Mono.error(unauthorized()))
                        .flatMap(
                                user ->
                                        db.sql(
                                                        "UPDATE tracking_user SET"
                                                            + " email_enabled=IF(verified_at IS"
                                                            + " NULL,true,email_enabled),verified_at=:now"
                                                            + " WHERE user_id=:user")
                                                .bind("now", now)
                                                .bind("user", user)
                                                .fetch()
                                                .rowsUpdated()
                                                .then(
                                                        db.sql(
                                                                        "INSERT INTO"
                                                                            + " tracking_session(session_hash,user_id,csrf_token,expires_at)"
                                                                            + " VALUES(:hash,:user,:csrf,:expires)")
                                                                .bind(
                                                                        "hash",
                                                                        TrackingRepository.hash(
                                                                                session))
                                                                .bind("user", user)
                                                                .bind("csrf", csrf)
                                                                .bind(
                                                                        "expires",
                                                                        now.plus(
                                                                                Duration.ofDays(
                                                                                        30)))
                                                                .fetch()
                                                                .rowsUpdated())
                                                .then(current(session)));
        return tx.transactional(work);
    }

    public Mono<Session> current(String token) {
        if (token == null || !token.matches("[A-Za-z0-9_-]{43}")) return Mono.empty();
        return db.sql(
                        "SELECT s.user_id,s.csrf_token,u.frequency FROM tracking_session s JOIN"
                            + " tracking_user u ON u.user_id=s.user_id WHERE s.session_hash=:hash"
                            + " AND s.expires_at>:now")
                .bind("hash", TrackingRepository.hash(token))
                .bind("now", clock.instant())
                .map(
                        (row, meta) ->
                                new Session(
                                        token,
                                        row.get("user_id", String.class),
                                        row.get("csrf_token", String.class),
                                        row.get("frequency", String.class)))
                .one();
    }

    public Mono<Me> me(String token) {
        return current(token)
                .flatMap(
                        session ->
                                follows(session.userId())
                                        .collectList()
                                        .map(
                                                follows ->
                                                        new Me(
                                                                true,
                                                                session.csrfToken(),
                                                                follows,
                                                                session.frequency())))
                .defaultIfEmpty(new Me(false, null, List.of(), "off"));
    }

    public Flux<Follow> follows(String user) {
        return db.sql(
                        "SELECT target_kind,target_id FROM tracking_follow WHERE user_id=:user"
                                + " ORDER BY target_kind,target_id")
                .bind("user", user)
                .map(
                        (row, meta) ->
                                new Follow(
                                        row.get("target_kind", String.class),
                                        row.get("target_id", String.class)))
                .all();
    }

    public Mono<Void> replaceFollows(String user, List<Follow> follows, String frequency) {
        TrackingPolicy.require(follows != null && follows.size() <= 20, "at most 20 follows");
        TrackingPolicy.require(
                List.of("weekly", "daily", "off").contains(frequency), "unsupported frequency");
        follows.forEach(
                follow -> {
                    TrackingPolicy.require(
                            follow != null
                                    && List.of("person", "topic", "bill", "issue")
                                            .contains(follow.kind()),
                            "unsupported follow kind");
                    TrackingPolicy.id(follow.targetId());
                });
        Mono<Void> work =
                db.sql("SELECT user_id FROM tracking_user WHERE user_id=:user FOR UPDATE")
                        .bind("user", user)
                        .fetch()
                        .one()
                        .switchIfEmpty(Mono.error(unauthorized()))
                        .thenMany(
                                Flux.fromIterable(follows)
                                        .distinct()
                                        .concatMap(this::validateTarget))
                        .then()
                        .then(
                                db.sql("DELETE FROM tracking_follow WHERE user_id=:user")
                                        .bind("user", user)
                                        .fetch()
                                        .rowsUpdated())
                        .thenMany(
                                Flux.fromIterable(follows)
                                        .distinct()
                                        .concatMap(
                                                follow ->
                                                        db.sql(
                                                                        "INSERT INTO"
                                                                            + " tracking_follow(user_id,target_kind,target_id)"
                                                                            + " VALUES(:user,:kind,:id)")
                                                                .bind("user", user)
                                                                .bind("kind", follow.kind())
                                                                .bind("id", follow.targetId())
                                                                .fetch()
                                                                .rowsUpdated()))
                        .then()
                        .then(
                                db.sql(
                                                "UPDATE tracking_user SET"
                                                    + " frequency=:frequency,email_enabled=:enabled"
                                                    + " WHERE user_id=:user")
                                        .bind("frequency", frequency)
                                        .bind("enabled", !frequency.equals("off"))
                                        .bind("user", user)
                                        .fetch()
                                        .rowsUpdated())
                        .then();
        return tx.transactional(work);
    }

    private Mono<Void> validateTarget(Follow follow) {
        if (follow.kind().equals("issue")) {
            issues.find(follow.targetId());
            return Mono.empty();
        }
        if (follow.kind().equals("topic")) {
            TrackingPolicy.require(
                    List.of("housing", "labor", "economy-tax", "family").contains(follow.targetId()),
                    "unknown topic target");
            return Mono.empty();
        }
        String sql =
                follow.kind().equals("person")
                        ? identities.hasStorage()?"SELECT 1 AS found FROM knowledge_entity k WHERE k.entity_kind='person' AND k.published=true AND " + identities.matches("k.entity_id",":id") + " LIMIT 1":"SELECT 1 AS found FROM parliament_person WHERE"
                                + " CONCAT('p_',SHA2(identity_key,256))=:id LIMIT 1"
                        : "SELECT 1 AS found FROM tracking_event_version WHERE bill_id=:id AND"
                                + " review_state='published' LIMIT 1";
        return db.sql(sql)
                .bind("id", follow.targetId())
                .fetch()
                .one()
                .switchIfEmpty(Mono.error(new IllegalArgumentException("unknown follow target")))
                .then();
    }

    public Mono<Void> logout(String token) {
        return db.sql("DELETE FROM tracking_session WHERE session_hash=:hash")
                .bind("hash", TrackingRepository.hash(token))
                .fetch()
                .rowsUpdated()
                .then();
    }

    public Mono<Void> unsubscribe(String token) {
        TrackingAuthPolicy.tokenFormat(token);
        Mono<Void> work =
                db.sql("SELECT user_id FROM tracking_user WHERE unsubscribe_hash=:hash FOR UPDATE")
                        .bind("hash", TrackingRepository.hash(token))
                        .map((row, meta) -> row.get("user_id", String.class))
                        .one()
                        .flatMap(
                                user ->
                                        db.sql(
                                                        "UPDATE tracking_user SET"
                                                            + " email_enabled=false,frequency='off'"
                                                            + " WHERE user_id=:user")
                                                .bind("user", user)
                                                .fetch()
                                                .rowsUpdated()
                                                .then(
                                                        db.sql(
                                                                        "UPDATE"
                                                                            + " tracking_mail_outbox"
                                                                            + " SET status='cancelled'"
                                                                            + " WHERE user_id=:user"
                                                                            + " AND mail_kind='digest'"
                                                                            + " AND status='queued'")
                                                                .bind("user", user)
                                                                .fetch()
                                                                .rowsUpdated())
                                                .then());
        return tx.transactional(work);
    }

    Mono<String> unsubscribeToken(String user) {
        return db.sql("SELECT unsubscribe_token FROM tracking_user WHERE user_id=:user")
                .bind("user", user)
                .map((row, metadata) -> row.get("unsubscribe_token", String.class))
                .one();
    }

    Mono<Void> queue(String user, String kind, String dedupe, Map<String, Object> payload) {
        String json;
        try {
            json = mapper.writeValueAsString(payload);
        } catch (com.fasterxml.jackson.core.JsonProcessingException ex) {
            throw new IllegalArgumentException("invalid mail payload", ex);
        }
        return db.sql(
                        "INSERT IGNORE INTO"
                            + " tracking_mail_outbox(mail_id,user_id,mail_kind,dedupe_key,payload)"
                            + " VALUES(:id,:user,:kind,:dedupe,:payload)")
                .bind("id", UUID.randomUUID().toString())
                .bind("user", user)
                .bind("kind", kind)
                .bind("dedupe", dedupe)
                .bind("payload", json)
                .fetch()
                .rowsUpdated()
                .then();
    }

    static ResponseStatusException unauthorized() {
        return new ResponseStatusException(
                HttpStatus.UNAUTHORIZED, "invalid or expired authentication");
    }
}
