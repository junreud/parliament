package dev.parliament.beta;

import dev.parliament.support.TestDatabase;
import io.r2dbc.spi.ConnectionFactories;
import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.DriverManager;
import java.time.Duration;
import java.time.Instant;
import org.junit.jupiter.api.*;
import org.springframework.r2dbc.connection.R2dbcTransactionManager;
import org.springframework.r2dbc.core.DatabaseClient;
import org.springframework.transaction.reactive.TransactionalOperator;
import org.springframework.web.server.ResponseStatusException;
import reactor.test.StepVerifier;
import static org.assertj.core.api.Assertions.*;

class BetaRepositoryTest {
    private static TestDatabase fixture;
    private static DatabaseClient db;
    private BetaRepository repository;
    private static final Instant AT = Instant.parse("2026-10-01T00:00:00Z");

    @BeforeAll
    static void initialize() throws Exception {
        fixture = TestDatabase.start("beta");
        try (var connection = DriverManager.getConnection(fixture.jdbcUrl(), fixture.username(), fixture.password());
             var statement = connection.createStatement()) {
            String schema = Files.readString(Path.of("src/main/resources/sql/schema-beta.sql"));
            for (String sql : schema.split(";")) if (!sql.isBlank()) statement.execute(sql);
        }
        db = DatabaseClient.create(ConnectionFactories.get(io.r2dbc.spi.ConnectionFactoryOptions.parse(fixture.r2dbcUrl()).mutate()
                .option(io.r2dbc.spi.ConnectionFactoryOptions.USER, fixture.username())
                .option(io.r2dbc.spi.ConnectionFactoryOptions.PASSWORD, fixture.password()).build()));
    }

    @AfterAll
    static void close() { if (fixture != null) fixture.close(); }

    @BeforeEach
    void setup() {
        db.sql("DELETE FROM beta_participant").fetch().rowsUpdated().block(Duration.ofSeconds(5));
        db.sql("DELETE FROM beta_acquisition").fetch().rowsUpdated().block(Duration.ofSeconds(5));
        var factory = ConnectionFactories.get(io.r2dbc.spi.ConnectionFactoryOptions.parse(fixture.r2dbcUrl()).mutate()
                .option(io.r2dbc.spi.ConnectionFactoryOptions.USER, fixture.username())
                .option(io.r2dbc.spi.ConnectionFactoryOptions.PASSWORD, fixture.password()).build());
        repository = new BetaRepository(DatabaseClient.create(factory),
                TransactionalOperator.create(new R2dbcTransactionManager(factory)), new BetaPolicy("http://localhost:3000"));
    }

    @Test
    void enrollmentHashesSessionKeepsContactsSeparateAndExpiryRejectsSession() {
        var enrolled = enroll(AT);
        assertThat(enrolled.token()).hasSize(43);
        var session = repository.current(enrolled.token(), AT).block();
        assertThat(session).isNotNull();
        assertThat(session.expiresAt()).isEqualTo(AT.plus(BetaPolicy.RETENTION));
        String hash = db.sql("SELECT session_hash FROM beta_participant").map((r,m) -> r.get("session_hash", String.class)).one().block();
        assertThat(hash).isNotEqualTo(enrolled.token()).hasSize(64);
        assertThat(count("beta_contact")).isEqualTo(1);
        StepVerifier.create(repository.current(enrolled.token(), AT.plus(BetaPolicy.RETENTION))).verifyComplete();
        StepVerifier.create(repository.current("bad", AT)).verifyComplete();
    }

    @Test
    void concurrentDuplicateBrowserEventsDedupAndWithdrawalCascades() {
        var session = repository.current(enroll(AT).token(), AT).block();
        var event = new BetaPolicy.Event("explainer_opened", "organic");
        reactor.core.publisher.Flux.range(0, 10).flatMap(i -> repository.record(session, event, AT)).then().block();
        assertThat(count("beta_event")).isEqualTo(1);
        repository.record(session, event, AT.plusSeconds(301)).block();
        assertThat(count("beta_event")).isEqualTo(2);
        repository.withdraw(session.participantId()).block();
        assertThat(count("beta_participant")).isZero();
        assertThat(count("beta_contact")).isZero();
        assertThat(count("beta_event")).isZero();
    }

    @Test
    void databaseReportMatchesMatureKoreanDayCohortsAndAnonymousCounts() {
        var session = repository.current(enroll(AT).token(), AT).block();
        repository.record(session, new BetaPolicy.Event("explainer_opened", "organic"), AT).block();
        repository.record(session, new BetaPolicy.Event("source_opened", "organic"), AT.plusSeconds(60)).block();
        repository.record(session, new BetaPolicy.Event("explainer_opened", "research"), AT.plus(Duration.ofDays(1))).block();
        repository.acquisition("instagram", AT).block();
        repository.acquisition("instagram", AT).block();
        var report = repository.report(AT.minus(Duration.ofHours(9)), AT.plus(Duration.ofDays(10)).minus(Duration.ofHours(9)), AT.plus(Duration.ofDays(8))).block();
        assertThat(report.cohorts().get(1).enrolled()).isEqualTo(1);
        assertThat(report.cohorts().get(1).activated()).isEqualTo(1);
        assertThat(report.cohorts().get(1).d7Eligible()).isEqualTo(1);
        assertThat(report.cohorts().get(1).organicReturned()).isZero();
        assertThat(report.cohorts().get(1).researchReturned()).isEqualTo(1);
        assertThat(report.acquisition().get("instagram")).isEqualTo(2);
    }

    @Test
    void retentionPurgeErasesContactEventsAndExpiredAttribution() {
        var session = repository.current(enroll(AT).token(), AT).block();
        repository.record(session, new BetaPolicy.Event("explainer_opened", "organic"), AT).block();
        repository.acquisition("network", AT).block();
        repository.purge(AT.plus(BetaPolicy.RETENTION).plus(Duration.ofDays(1))).block();
        assertThat(count("beta_participant")).isZero();
        assertThat(count("beta_contact")).isZero();
        assertThat(count("beta_event")).isZero();
        assertThat(count("beta_acquisition")).isZero();
    }

    @Test
    void contactWriteFailureRollsBackThePseudonymousEnrollment() {
        // Exceeds the actual contact column; all data is synthetic inside the disposable schema.
        StepVerifier.create(repository.enroll(new BetaPolicy.Enrollment("x".repeat(255), "external", "direct"), AT))
                .expectErrorSatisfies(error -> {
                    assertThat(error).isInstanceOf(ResponseStatusException.class);
                    assertThat(((ResponseStatusException)error).getStatusCode().value()).isEqualTo(503);
                }).verify();
        assertThat(count("beta_participant")).isZero();
        assertThat(count("beta_contact")).isZero();
    }

    @Test
    void expiredConsentCannotAcceptEventsEvenWithFormerValidSession() {
        var session = repository.current(enroll(AT).token(), AT).block();
        repository.record(session, new BetaPolicy.Event("explainer_opened", "organic"), AT.plus(BetaPolicy.RETENTION)).block();
        assertThat(count("beta_event")).isZero();
    }

    @Test
    void retentionDeletesWithinSafetyWindowBeforeMaximumThirtyFiveDays() {
        var session = repository.current(enroll(AT).token(), AT).block();
        repository.record(session, new BetaPolicy.Event("explainer_opened", "organic"), AT).block();
        repository.purge(AT.plus(BetaPolicy.RETENTION).minus(Duration.ofHours(1)).minusSeconds(1)).block();
        assertThat(count("beta_participant")).isEqualTo(1);
        repository.purge(AT.plus(BetaPolicy.RETENTION).minus(Duration.ofHours(1))).block();
        assertThat(count("beta_participant")).isZero();
        assertThat(count("beta_contact")).isZero();
        assertThat(count("beta_event")).isZero();
    }

    @Test
    void reportRejectsPartialDaysAndUsesIdenticalKoreanDayAcquisitionBoundaries() {
        StepVerifier.create(repository.report(AT, AT.plus(Duration.ofDays(1)), AT))
                .expectError(IllegalArgumentException.class).verify();
        Instant midnight = AT.minus(Duration.ofHours(9));
        enroll(midnight.minusSeconds(1));
        enroll(midnight);
        enroll(midnight.plus(Duration.ofDays(1)));
        repository.acquisition("instagram", midnight.minusSeconds(1)).block();
        repository.acquisition("instagram", midnight).block();
        repository.acquisition("instagram", midnight.plus(Duration.ofDays(1))).block();
        var report = repository.report(midnight, midnight.plus(Duration.ofDays(1)), AT.plus(Duration.ofDays(2))).block();
        assertThat(report.cohorts().get(1).enrolled()).isEqualTo(1);
        assertThat(report.acquisition().get("instagram")).isEqualTo(1);
    }

    @Test
    void retentionSkipsMissingSchemaSafely() throws Exception {
        try {
            for (String table : java.util.List.of("beta_event", "beta_contact", "beta_participant", "beta_acquisition"))
                db.sql("DROP TABLE " + table).fetch().rowsUpdated().block();
            new BetaRetention(db).purge(AT).block();
        } finally {
            try (var connection = DriverManager.getConnection(fixture.jdbcUrl(), fixture.username(), fixture.password());
                 var statement = connection.createStatement()) {
                String schema = Files.readString(Path.of("src/main/resources/sql/schema-beta.sql"));
                for (String sql : schema.split(";")) if (!sql.isBlank()) statement.execute(sql);
            }
        }
    }

    @Test
    void invalidReportRangeFailsBeforeDatabaseAccess() {
        StepVerifier.create(repository.report(AT, AT, AT)).expectError(IllegalArgumentException.class).verify();
        StepVerifier.create(repository.report(AT, AT.plus(Duration.ofDays(36)), AT))
                .expectError(IllegalArgumentException.class).verify();
    }

    private BetaRepository.Enrolled enroll(Instant at) {
        return repository.enroll(new BetaPolicy.Enrollment("fake@example.org", "external", "instagram"), at).block();
    }
    private long count(String table) {
        // Table names are test constants, never request values.
        return db.sql("SELECT COUNT(*) AS amount FROM " + table)
                .map((r,m) -> ((Number)r.get("amount")).longValue()).one().block();
    }
}
