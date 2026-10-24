package dev.parliament.tracking;

import static org.assertj.core.api.Assertions.*;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;

import io.r2dbc.spi.ConnectionFactories;

import org.junit.jupiter.api.*;
import org.springframework.core.io.ClassPathResource;
import org.springframework.jdbc.datasource.init.ScriptUtils;
import org.springframework.r2dbc.connection.R2dbcTransactionManager;
import org.springframework.r2dbc.core.DatabaseClient;
import org.springframework.transaction.reactive.TransactionalOperator;
import dev.parliament.support.TestDatabase;

import java.sql.DriverManager;
import java.util.List;

class TrackingRepositoryTest {
    private static TestDatabase MYSQL;
    private TrackingRepository repository;
    private DatabaseClient db;

    @BeforeAll
    static void start() {
        MYSQL = TestDatabase.start("tracking");
    }

    @AfterAll
    static void stop() {
        if (MYSQL != null) MYSQL.close();
    }

    @BeforeEach
    void setup() throws Exception {
        try (var c =
                DriverManager.getConnection(
                        MYSQL.jdbcUrl(), MYSQL.username(), MYSQL.password())) {
            for (String table :
                    List.of(
                            "tracking_review_budget",
                            "tracking_auth_rate",
                            "tracking_digest_item",
                            "tracking_mail_outbox",
                            "tracking_follow",
                            "tracking_session",
                            "tracking_login_token",
                            "tracking_user",
                            "tracking_event_topic",
                            "tracking_event_person",
                            "tracking_event_version",
                            "tracking_event")) {
                c.createStatement().execute("DROP TABLE IF EXISTS " + table);
            }
            ScriptUtils.executeSqlScript(c, new ClassPathResource("sql/reset-parliament.sql"));
            ScriptUtils.executeSqlScript(c, new ClassPathResource("sql/schema-parliament.sql"));
            ScriptUtils.executeSqlScript(c, new ClassPathResource("sql/schema-tracking.sql"));
        }
        var factory = ConnectionFactories.get(MYSQL.r2dbcUrl());
        db = DatabaseClient.create(factory);
        repository =
                new TrackingRepository(
                        db,
                        TransactionalOperator.create(new R2dbcTransactionManager(factory)),
                        new ObjectMapper().registerModule(new JavaTimeModule()));
    }

    @Test
    void explicitVoteProjectionRetainsParticipantsAndDirectoryCoverageShowsUncollectedSources() {
        var mapper = new ObjectMapper().registerModule(new JavaTimeModule());
        for (int i = 1; i <= 2; i++) {
            String identity = "member:" + i;
            db.sql(
                            "INSERT INTO"
                                + " parliament_person(identity_key,canonical_name,person_kind,resolution_status)"
                                + " VALUES(:id,:name,'LEGISLATOR','RESOLVED')")
                    .bind("id", identity)
                    .bind("name", "표본 의원 " + i)
                    .fetch()
                    .rowsUpdated()
                    .block();
            db.sql(
                            "INSERT INTO"
                                + " parliament_person_identifier(identifier_namespace,external_id,identity_key)"
                                + " VALUES('VERIFIED_MEMBER',:external,:id)")
                    .bind("external", "M" + i)
                    .bind("id", identity)
                    .fetch()
                    .rowsUpdated()
                    .block();
            String raw =
                    "{\"ID\":\"r"
                            + i
                            + "\",\"TITLE\":\"표본 법안 표결\",\"BILL\":\"B1\",\"MEMBER\":\"M"
                            + i
                            + "\",\"VOTE\":\""
                            + (i == 1 ? "찬성" : "미공개")
                            + "\",\"SESSION\":\"S1\",\"DATE\":\"2026-10-01\",\"URL\":\"https://open.assembly.go.kr/x\"}";
            db.sql(
                            "INSERT INTO"
                                + " parliament_source_record(source_key,record_key,api_code,payload_hash,raw_payload)"
                                + " VALUES('votes',:record,'votes',:hash,:raw)")
                    .bind("record", "r" + i)
                    .bind("hash", String.valueOf(i).repeat(40))
                    .bind("raw", raw)
                    .fetch()
                    .rowsUpdated()
                    .block();
        }
        var contract =
                new TrackingProjection.Contract(
                        "votes",
                        "vote",
                        true,
                        java.util.Map.of(
                                "id",
                                "ID",
                                "title",
                                "TITLE",
                                "url",
                                "URL",
                                "publishedAt",
                                "DATE",
                                "personId",
                                "MEMBER",
                                "billId",
                                "BILL",
                                "sessionId",
                                "SESSION",
                                "voteResult",
                                "VOTE"),
                        java.util.Map.of(),
                        java.util.Map.of("찬성", "yes"),
                        "VERIFIED_MEMBER",
                        List.of("housing", "rental-protection"),
                        20);
        var projection = new TrackingProjection(db, repository, mapper);
        var projectionResult = projection.project(contract).block();
        assertThat(projectionResult.imported())
                .as(projectionResult.notes().toString())
                .isEqualTo(1);
        repository
                .drafts()
                .collectList()
                .block()
                .forEach(a -> repository.publish(a.id(), a.version(), "reviewer", "").block());
        var directory = new TrackingDirectory(db, repository);
        var bill = directory.bill("b_" + TrackingRepository.hash("B1")).block();
        assertThat(bill.votes())
                .extracting(Activity.Vote::result)
                .containsExactlyInAnyOrder("yes", "unknown");
        assertThat(directory.people(null).collectList().block()).hasSize(2);
        assertThat(directory.coverage().collectList().block())
                .anyMatch(source -> source.status().equals("not-collected"));
    }

    @Test
    void newlyVisibleChangesSortAheadOfNewerOriginalSourceDatesAndReplayIgnoresDerivedMetadata()
            throws Exception {
        var mapper = new ObjectMapper().registerModule(new JavaTimeModule());
        Activity newer =
                TrackingPolicyTest.activity(
                        "https://open.assembly.go.kr/x", "BILL_ID=b1", "unknown");
        var tree = (com.fasterxml.jackson.databind.node.ObjectNode) mapper.valueToTree(newer);
        tree.put("id", "older_source").put("publishedAt", "2020-01-01T00:00:00Z");
        Activity older = mapper.treeToValue(tree, Activity.class);
        repository.importDraft(newer).block();
        repository.publish(newer.id(), newer.version(), "reviewer", "").block();
        repository.importDraft(older).block();
        repository.publish(older.id(), older.version(), "reviewer", "").block();
        var first = repository.feed(null, null, null, null, null, null, 1).block();
        assertThat(first.items().get(0).id()).isEqualTo(older.id());
        assertThat(first.items().get(0).publishedAt()).isEqualTo(older.publishedAt());
        assertThat(first.items().get(0).changedAt()).isNotNull();
        var second =
                repository
                        .feed(
                                null,
                                null,
                                null,
                                null,
                                null,
                                TrackingCursor.decode(first.nextCursor()),
                                1)
                        .block();
        assertThat(second.items().get(0).id()).isEqualTo(newer.id());
        assertThat(repository.importDraft(first.items().get(0)).block().replayed()).isTrue();
    }

    @Test
    void loginTokenIsOneUseAndFollowsAreValidatedAndUnsubscribeStopsFutureQueueing()
            throws Exception {
        var auth =
                new TrackingAuthRepository(
                        db,
                        repository,
                        new ObjectMapper().registerModule(new JavaTimeModule()),
                        new TrackingAuthPolicy("http://localhost:3000"),
                        java.time.Clock.systemUTC(),
                        new TrackingIssues(),
                        TransactionalOperator.create(
                                new R2dbcTransactionManager(db.getConnectionFactory())));
        auth.requestLink("user@example.test", "client").block();
        String payload =
                db.sql("SELECT payload FROM tracking_mail_outbox WHERE mail_kind='login'")
                        .map((row, meta) -> row.get("payload", String.class))
                        .one()
                        .block();
        String link = new ObjectMapper().readTree(payload).get("loginUrl").asText();
        String token = link.substring(link.lastIndexOf("=") + 1);
        var session = auth.verify(token).block();
        assertThat(session.token()).isNotEqualTo(token);
        assertThatThrownBy(() -> auth.verify(token).block())
                .hasMessageContaining("invalid or expired");
        assertThat(auth.current(session.token()).block().userId()).isEqualTo(session.userId());
        auth.replaceFollows(
                        session.userId(),
                        List.of(new TrackingAuthRepository.Follow("topic", "housing")),
                        "weekly")
                .block();
        assertThat(auth.me(session.token()).block().follows()).hasSize(1);
        assertThatThrownBy(
                        () ->
                                auth.replaceFollows(
                                                session.userId(),
                                                List.of(
                                                        new TrackingAuthRepository.Follow(
                                                                "person", "p_missing")),
                                                "weekly")
                                        .block())
                .hasMessageContaining("target");
        auth.unsubscribe(auth.unsubscribeToken(session.userId()).block()).block();
        assertThat(auth.me(session.token()).block().frequency()).isEqualTo("off");
    }

    @Test
    void digestIsVersionDeduplicatedAndUnsubscribeCancelsQueuedDigests() throws Exception {
        var tx =
                TransactionalOperator.create(
                        new R2dbcTransactionManager(db.getConnectionFactory()));
        var mapper = new ObjectMapper().registerModule(new JavaTimeModule());
        var auth =
                new TrackingAuthRepository(
                        db,
                        repository,
                        mapper,
                        new TrackingAuthPolicy("http://localhost:3000"),
                        java.time.Clock.systemUTC(),
                        new TrackingIssues(),
                        tx);
        auth.requestLink("digest@example.test", "client").block();
        String payload =
                db.sql("SELECT payload FROM tracking_mail_outbox WHERE mail_kind='login'")
                        .map((row, meta) -> row.get("payload", String.class))
                        .one()
                        .block();
        String link = mapper.readTree(payload).get("loginUrl").asText();
        var session = auth.verify(link.substring(link.lastIndexOf("=") + 1)).block();
        auth.replaceFollows(
                        session.userId(),
                        List.of(new TrackingAuthRepository.Follow("topic", "housing")),
                        "weekly")
                .block();
        Activity event =
                TrackingPolicyTest.activity(
                        "https://open.assembly.go.kr/x", "BILL_ID=b1", "unknown");
        repository.importDraft(event).block();
        repository.publish(event.id(), event.version(), "reviewer", "").block();
        var digests =
                new TrackingDigests(
                        db, repository, auth, new TrackingAuthPolicy("http://localhost:3000"), tx);
        assertThat(
                        digests.build(
                                        "weekly",
                                        java.time.Instant.EPOCH,
                                        java.time.Instant.now().plusSeconds(60))
                                .block()
                                .queued())
                .isEqualTo(1);
        assertThat(
                        digests.build(
                                        "weekly",
                                        java.time.Instant.EPOCH,
                                        java.time.Instant.now().plusSeconds(60))
                                .block()
                                .queued())
                .isZero();
        var restarted =
                new TrackingAuthRepository(
                        db,
                        repository,
                        mapper,
                        new TrackingAuthPolicy("http://localhost:3000"),
                        java.time.Clock.systemUTC(),
                        new TrackingIssues(),
                        tx);
        assertThat(restarted.unsubscribeToken(session.userId()).block())
                .isEqualTo(auth.unsubscribeToken(session.userId()).block());
        auth.unsubscribe(auth.unsubscribeToken(session.userId()).block()).block();
        assertThat(
                        db.sql("SELECT status FROM tracking_mail_outbox WHERE mail_kind='digest'")
                                .map((row, meta) -> row.get("status", String.class))
                                .one()
                                .block())
                .isEqualTo("cancelled");
        assertThat(
                        digests.build(
                                        "weekly",
                                        java.time.Instant.EPOCH,
                                        java.time.Instant.now().plusSeconds(60))
                                .block()
                                .queued())
                .isZero();
    }

    @Test
    void freeTextReviewQuotaDoesNotLimitStructuralFacts() {
        Activity base =
                TrackingPolicyTest.activity(
                        "https://open.assembly.go.kr/x", "BILL_ID=b1", "unknown");
        for (int i = 0; i < 5; i++) {
            Activity a =
                    new Activity(
                            "event_" + i,
                            base.type(),
                            base.title(),
                            i < 4 ? "검수 설명" : null,
                            base.stage(),
                            base.personIds(),
                            base.topics(),
                            base.billId(),
                            base.occurredAt(),
                            base.publishedAt(),
                            base.collectedAt(),
                            base.sourceUrl(),
                            base.evidence(),
                            base.votes(),
                            base.coverage(),
                            false,
                            "v1");
            repository.importDraft(a).block();
            if (i == 3)
                assertThatThrownBy(() -> repository.publish(a.id(), "v1", "reviewer", "").block())
                        .hasMessageContaining("daily");
            else repository.publish(a.id(), "v1", "reviewer", "").block();
        }
        assertThat(repository.feed(null, null, null, null, null, null, 20).block().items())
                .hasSize(4);
    }

    @Test
    void draftsNeverAppearAndReplayIsIdempotentAndConflictingRevisionRejected() {
        Activity activity =
                TrackingPolicyTest.activity(
                        "https://open.assembly.go.kr/x", "BILL_ID=b1", "unknown");
        assertThat(repository.importDraft(activity).block().replayed()).isFalse();
        assertThat(repository.importDraft(activity).block().replayed()).isTrue();
        assertThat(repository.feed(null, null, null, null, null, null, 20).block().items())
                .isEmpty();
        assertThatThrownBy(
                        () ->
                                repository
                                        .importDraft(activity.explained("different", false))
                                        .block())
                .hasMessageContaining("immutable");
        repository.publish(activity.id(), activity.version(), "test reviewer", "").block();
        assertThat(repository.feed(null, null, null, null, null, null, 20).block().items())
                .hasSize(1);
        assertThat(repository.detail(activity.id(), null).block().votes().get(0).result())
                .isEqualTo("unknown");
    }

    @Test
    void correctionPreservesPriorPublishedVersionAndCursorMatchesFilters() {
        Activity one =
                TrackingPolicyTest.activity(
                        "https://open.assembly.go.kr/x", "BILL_ID=b1", "unknown");
        repository.importDraft(one).block();
        repository.publish(one.id(), one.version(), "reviewer", "").block();
        Activity two =
                new Activity(
                        one.id(),
                        one.type(),
                        one.title(),
                        "정정된 설명",
                        one.stage(),
                        one.personIds(),
                        one.topics(),
                        one.billId(),
                        one.occurredAt(),
                        one.publishedAt(),
                        one.collectedAt(),
                        one.sourceUrl(),
                        one.evidence(),
                        one.votes(),
                        one.coverage(),
                        true,
                        "v2");
        repository.importDraft(two).block();
        repository.publish(two.id(), "v2", "reviewer", "설명 정정").block();
        assertThat(repository.detail(one.id(), null).block().corrected()).isTrue();
        assertThat(repository.detail(one.id(), "v1").block().summary()).isNull();
        Activity draft =
                new Activity(
                        one.id(),
                        one.type(),
                        one.title(),
                        null,
                        one.stage(),
                        one.personIds(),
                        one.topics(),
                        one.billId(),
                        one.occurredAt(),
                        one.publishedAt(),
                        one.collectedAt(),
                        one.sourceUrl(),
                        one.evidence(),
                        one.votes(),
                        one.coverage(),
                        false,
                        "v3");
        repository.importDraft(draft).block();
        repository.reject(one.id(), "v3").block();
        Activity pending =
                new Activity(
                        one.id(),
                        one.type(),
                        one.title(),
                        null,
                        one.stage(),
                        one.personIds(),
                        one.topics(),
                        one.billId(),
                        one.occurredAt(),
                        one.publishedAt(),
                        one.collectedAt(),
                        one.sourceUrl(),
                        one.evidence(),
                        one.votes(),
                        one.coverage(),
                        false,
                        "v4");
        repository.importDraft(pending).block();
        var history = repository.history(one.id()).collectList().block();
        assertThat(history)
                .extracting(TrackingRepository.History::version)
                .containsExactly("v2", "v1");
        assertThat(history.get(0).correctionReason()).isEqualTo("설명 정정");
        assertThat(repository.feed("other", null, null, null, null, null, 20).block().items())
                .isEmpty();
        assertThat(
                        repository
                                .feed(
                                        null,
                                        "housing",
                                        null,
                                        null,
                                        null,
                                        new TrackingCursor(one.publishedAt(), one.id()),
                                        20)
                                .block()
                                .items())
                .isEmpty();
    }
}
