package dev.parliament.persistence;

import dev.parliament.config.ParliamentCollectionMode;
import dev.parliament.config.ParliamentMediaType;
import dev.parliament.config.ParliamentSourceDefinition;
import dev.parliament.domain.NormalizedParliamentRecord;
import dev.parliament.domain.PersonCandidate;
import dev.parliament.domain.PersonKind;
import dev.parliament.domain.PersonResolutionStatus;
import dev.parliament.domain.SocialAccount;
import dev.parliament.domain.SocialPlatform;
import dev.parliament.domain.SocialVerificationStatus;
import dev.parliament.domain.SocialUrlVerificationStatus;
import io.r2dbc.spi.ConnectionFactories;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.core.io.ClassPathResource;
import org.springframework.jdbc.datasource.init.ScriptUtils;
import org.springframework.r2dbc.connection.R2dbcTransactionManager;
import org.springframework.r2dbc.core.DatabaseClient;
import org.springframework.transaction.reactive.TransactionalOperator;
import org.testcontainers.mysql.MySQLContainer;
import reactor.test.StepVerifier;

import java.sql.DriverManager;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

class R2dbcParliamentStagingRepositoryTest {
    private static MySQLContainer mysql;
    private static String jdbcUrl;
    private static String r2dbcUrl;
    private static String username;
    private static String password;

    private DatabaseClient databaseClient;
    private R2dbcParliamentStagingRepository repository;

    @BeforeAll
    static void startDatabase() {
        String externalJdbcUrl = System.getenv("PARLIAMENT_TEST_JDBC_URL");
        if (externalJdbcUrl != null && !externalJdbcUrl.isBlank()) {
            jdbcUrl = externalJdbcUrl;
            r2dbcUrl = requiredEnvironment("PARLIAMENT_TEST_R2DBC_URL");
            username = requiredEnvironment("PARLIAMENT_TEST_DB_USER");
            password = requiredEnvironment("PARLIAMENT_TEST_DB_PASSWORD");
            return;
        }
        mysql = new MySQLContainer("mysql:8.4")
                .withDatabaseName("parliament")
                .withUsername("parliament")
                .withPassword("test-password");
        mysql.start();
        jdbcUrl = mysql.getJdbcUrl();
        username = mysql.getUsername();
        password = mysql.getPassword();
        r2dbcUrl = "r2dbc:mysql://" + username + ":" + password
                + "@" + mysql.getHost() + ":" + mysql.getMappedPort(3306)
                + "/" + mysql.getDatabaseName();
    }

    @AfterAll
    static void stopDatabase() {
        if (mysql != null) {
            mysql.stop();
        }
    }

    @BeforeEach
    void setUp() throws Exception {
        try (var connection = DriverManager.getConnection(
                jdbcUrl, username, password)) {
            ScriptUtils.executeSqlScript(connection, new ClassPathResource("sql/reset-parliament.sql"));
            ScriptUtils.executeSqlScript(connection, new ClassPathResource("sql/schema-parliament.sql"));
        }
        var connectionFactory = ConnectionFactories.get(r2dbcUrl);
        databaseClient = DatabaseClient.create(connectionFactory);
        repository = new R2dbcParliamentStagingRepository(
                databaseClient,
                TransactionalOperator.create(new R2dbcTransactionManager(connectionFactory)));
    }

    @Test
    void savesNormalisedPageAndAdvancesCheckpointInOneTransaction() throws Exception {
        ParliamentSourceDefinition source = new ParliamentSourceDefinition(
                "allnamember", "ALLNAMEMBER", "국회의원 정보 통합 API", "15126133",
                ParliamentMediaType.DATA, ParliamentCollectionMode.PAGE, Map.of());
        SocialAccount social = new SocialAccount(
                SocialPlatform.X, "https://x.com/hong", "hong", true,
                SocialVerificationStatus.OFFICIAL_DIRECTORY);
        PersonCandidate person = new PersonCandidate(
                "assembly-member:a001", "홍길동", PersonKind.LEGISLATOR, "A001",
                "국회의원", "대한민국 국회", PersonResolutionStatus.VERIFIED_EXTERNAL_ID,
                List.of(social));
        NormalizedParliamentRecord record = new NormalizedParliamentRecord(
                "A001", "0123456789012345678901234567890123456789",
                "{\"NAAS_CD\":\"A001\",\"GTELT_ERACO\":\"제21대, 제22대\"}", List.of(person));

        StepVerifier.create(repository.savePage(source, List.of(record), 1, 2, false)
                        .then(repository.checkpoint(source.key(), source.variantKey())))
                .expectNextMatches(checkpoint -> checkpoint.nextPage() == 2 && !checkpoint.complete())
                .verifyComplete();

        StepVerifier.create(count("parliament_person"))
                .assertNext(count -> assertThat(count).isEqualTo(1L))
                .verifyComplete();
        StepVerifier.create(count("parliament_social_account"))
                .assertNext(count -> assertThat(count).isEqualTo(1L))
                .verifyComplete();
        StepVerifier.create(count("parliament_record_person"))
                .assertNext(count -> assertThat(count).isEqualTo(1L))
                .verifyComplete();

        SocialAccount replacement = new SocialAccount(
                SocialPlatform.X, "https://x.com/hong-new", "hong-new", true,
                SocialVerificationStatus.OFFICIAL_DIRECTORY);
        PersonCandidate updatedPerson = person.withSocialAccounts(List.of(replacement));
        NormalizedParliamentRecord secondRecord = new NormalizedParliamentRecord(
                "A001-2", "abcdefabcdefabcdefabcdefabcdefabcdefabcd",
                "{\"NAAS_CD\":\"A001\",\"SEQ\":2}", List.of(updatedPerson));

        StepVerifier.create(repository.savePage(source, List.of(secondRecord), 2, 2, true)
                        .then(repository.checkpoint(source.key(), source.variantKey())))
                .expectNextMatches(checkpoint -> checkpoint.complete() && checkpoint.nextPage() == 2)
                .verifyComplete();
        StepVerifier.create(databaseClient.sql("""
                                SELECT COUNT(*) AS count_value
                                FROM parliament_social_account
                                WHERE identity_key = 'assembly-member:a001' AND is_primary = true
                                """)
                        .map((row, metadata) -> row.get("count_value", Long.class))
                        .one())
                .expectNext(1L)
                .verifyComplete();

        PersonCandidate formerPerson = new PersonCandidate(
                "assembly-member:a002", "김전직", PersonKind.LEGISLATOR, "A002",
                "국회의원", "대한민국 국회", PersonResolutionStatus.VERIFIED_EXTERNAL_ID,
                List.of());
        NormalizedParliamentRecord formerRecord = new NormalizedParliamentRecord(
                "A002", "1111111111111111111111111111111111111111",
                "{\"NAAS_CD\":\"A002\",\"GTELT_ERACO\":\"제20대\"}", List.of(formerPerson));
        StepVerifier.create(repository.savePage(source, List.of(formerRecord), 3, 3, true))
                .verifyComplete();

        ParliamentSourceDefinition currentRoster = new ParliamentSourceDefinition(
                "nwvrqwxyaytdsfvhu", "nwvrqwxyaytdsfvhu", "국회의원 인적사항", null,
                ParliamentMediaType.DATA, ParliamentCollectionMode.PAGE, Map.of());
        NormalizedParliamentRecord currentRecord = new NormalizedParliamentRecord(
                "A001", "2222222222222222222222222222222222222222",
                "{\"MONA_CD\":\"A001\",\"UNITS\":\"제21대, 제22대\"}", List.of(person));
        StepVerifier.create(repository.savePage(currentRoster, List.of(currentRecord), 1, 1, true))
                .verifyComplete();

        try (var connection = DriverManager.getConnection(jdbcUrl, username, password)) {
            ScriptUtils.executeSqlScript(connection,
                    new ClassPathResource("sql/migrations/002-legislator-term-status-up.sql"));
        }
        StepVerifier.create(repository.finalizeSourceSnapshot(
                        currentRoster.key(), java.time.Instant.EPOCH))
                .expectNext(0)
                .verifyComplete();

        StepVerifier.create(text("""
                        SELECT membership_status
                        FROM parliament_legislator_status
                        WHERE identity_key = 'assembly-member:a001'
                        """))
                .expectNext("CURRENT")
                .verifyComplete();
        StepVerifier.create(text("""
                        SELECT membership_status
                        FROM parliament_legislator_status
                        WHERE identity_key = 'assembly-member:a002'
                        """))
                .expectNext("FORMER")
                .verifyComplete();
        StepVerifier.create(countWhere("parliament_legislator_term",
                        "identity_key = 'assembly-member:a001'"))
                .expectNext(2L)
                .verifyComplete();
        StepVerifier.create(count("parliament_current_legislator"))
                .expectNext(1L)
                .verifyComplete();
        StepVerifier.create(count("parliament_former_legislator"))
                .expectNext(1L)
                .verifyComplete();
    }

    @Test
    void incrementalPageWritesOnlyNewOrChangedPayloadsAndKeepsVariantCheckpointsSeparate() {
        ParliamentSourceDefinition firstVariant = new ParliamentSourceDefinition(
                "allbill", "allbill", "의안 상세", null,
                ParliamentMediaType.DATA, ParliamentCollectionMode.PAGE, Map.of("BILL_NO", "1"));
        ParliamentSourceDefinition secondVariant = firstVariant.withFixedParams(Map.of("BILL_NO", "2"));
        NormalizedParliamentRecord original = new NormalizedParliamentRecord(
                "bill-1", "1111111111111111111111111111111111111111", "{\"BILL_ID\":\"bill-1\"}", List.of());

        StepVerifier.create(repository.saveChangedPage(firstVariant, List.of(original), 1, 1, true))
                .assertNext(result -> {
                    assertThat(result.changed()).isEqualTo(1);
                    assertThat(result.unchanged()).isZero();
                })
                .verifyComplete();
        StepVerifier.create(repository.saveChangedPage(firstVariant, List.of(original), 1, 1, true))
                .assertNext(result -> {
                    assertThat(result.changed()).isZero();
                    assertThat(result.unchanged()).isEqualTo(1);
                })
                .verifyComplete();

        NormalizedParliamentRecord changed = new NormalizedParliamentRecord(
                "bill-1", "2222222222222222222222222222222222222222", "{\"BILL_ID\":\"bill-1\",\"x\":1}", List.of());
        StepVerifier.create(repository.saveChangedPage(firstVariant, List.of(changed), 1, 1, true))
                .assertNext(result -> assertThat(result.changed()).isEqualTo(1))
                .verifyComplete();
        StepVerifier.create(repository.savePage(secondVariant, List.of(), 1, 1, true))
                .verifyComplete();

        StepVerifier.create(countWhere("parliament_ingestion_checkpoint", "source_key = 'allbill'"))
                .expectNext(2L)
                .verifyComplete();
        StepVerifier.create(repository.distinctRawValuesChangedSince(
                        "allbill", "BILL_ID", java.time.Instant.EPOCH, 10))
                .expectNext("bill-1")
                .verifyComplete();

        java.time.Instant started = java.time.Instant.parse("2026-09-09T00:00:00Z");
        java.time.Instant finished = java.time.Instant.parse("2026-09-09T00:01:00Z");
        StepVerifier.create(repository.markSourceSyncStarted("allbill", started)
                        .then(repository.markSourceSyncCompleted("allbill", started, finished))
                        .then(repository.lastSuccessfulSyncAt("allbill")))
                .expectNext(started)
                .verifyComplete();
    }

    @Test
    void storesOfficialDirectoryEvidenceSeparatelyFromUrlHealth() {
        ParliamentSourceDefinition officialDirectory = new ParliamentSourceDefinition(
                "negnlnyvatsjwocar", "negnlnyvatsjwocar", "국회의원 SNS", null,
                ParliamentMediaType.DATA, ParliamentCollectionMode.PAGE, Map.of());
        SocialAccount social = new SocialAccount(
                SocialPlatform.X, "https://x.com/member", "member", true,
                SocialVerificationStatus.OFFICIAL_DIRECTORY);
        PersonCandidate person = new PersonCandidate(
                "assembly-member:a100", "홍길동", PersonKind.LEGISLATOR, "A100",
                "국회의원", "대한민국 국회", PersonResolutionStatus.VERIFIED_EXTERNAL_ID,
                List.of(social));
        NormalizedParliamentRecord record = new NormalizedParliamentRecord(
                "A100", "3333333333333333333333333333333333333333", "{\"MONA_CD\":\"A100\"}", List.of(person));
        StepVerifier.create(repository.savePage(officialDirectory, List.of(record), 1, 1, true))
                .verifyComplete();

        StepVerifier.create(repository.findDue(java.time.Instant.parse("2026-09-09T00:00:00Z"), 10))
                .assertNext(target -> assertThat(target.canonicalUrl()).isEqualTo("https://x.com/member"))
                .verifyComplete();
        SocialAccountVerificationTarget target = new SocialAccountVerificationTarget(
                "assembly-member:a100", SocialPlatform.X, dev.parliament.util.TextUtil.textSha1("https://x.com/member"),
                "https://x.com/member");
        SocialAccountVerification verification = new SocialAccountVerification(
                target, SocialUrlVerificationStatus.REACHABLE, 200,
                "https://x.com/member", null, java.time.Instant.parse("2026-09-09T01:00:00Z"));
        StepVerifier.create(repository.saveVerification(verification)).verifyComplete();

        StepVerifier.create(databaseClient.sql("""
                        SELECT CONCAT(verification_status, ':', official_evidence_source_key, ':', url_verification_status)
                          AS verification_value
                        FROM parliament_social_account
                        WHERE identity_key = 'assembly-member:a100'
                        """)
                .map((row, metadata) -> row.get("verification_value", String.class)).one())
                .expectNext("OFFICIAL_DIRECTORY:negnlnyvatsjwocar:REACHABLE")
                .verifyComplete();

        StepVerifier.create(databaseClient.sql("""
                        UPDATE parliament_source_record
                        SET last_seen_at = '2020-01-01 00:00:00'
                        WHERE source_key = 'negnlnyvatsjwocar' AND record_key = 'A100'
                        """).fetch().rowsUpdated()).expectNext(1L).verifyComplete();
        StepVerifier.create(repository.finalizeSourceSnapshot(
                        "negnlnyvatsjwocar", java.time.Instant.parse("2021-01-01T00:00:00Z")))
                .expectNext(1)
                .verifyComplete();
        StepVerifier.create(databaseClient.sql("""
                        SELECT verification_status
                        FROM parliament_social_account
                        WHERE identity_key = 'assembly-member:a100'
                        """)
                .map((row, metadata) -> row.get("verification_status", String.class)).one())
                .expectNext("UNVERIFIED")
                .verifyComplete();
    }

    private reactor.core.publisher.Mono<Long> count(String table) {
        return databaseClient.sql("SELECT COUNT(*) AS count_value FROM " + table)
                .map((row, metadata) -> row.get("count_value", Long.class))
                .one();
    }

    private reactor.core.publisher.Mono<Long> countWhere(String table, String where) {
        return databaseClient.sql("SELECT COUNT(*) AS count_value FROM " + table + " WHERE " + where)
                .map((row, metadata) -> row.get("count_value", Long.class))
                .one();
    }

    private reactor.core.publisher.Mono<String> text(String sql) {
        return databaseClient.sql(sql)
                .map((row, metadata) -> row.get("membership_status", String.class))
                .one();
    }

    private static String requiredEnvironment(String name) {
        String value = System.getenv(name);
        if (value == null || value.isBlank()) {
            throw new IllegalStateException(name + " is required with PARLIAMENT_TEST_JDBC_URL");
        }
        return value;
    }
}
