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
import io.r2dbc.spi.ConnectionFactories;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.core.io.ClassPathResource;
import org.springframework.jdbc.datasource.init.ScriptUtils;
import org.springframework.r2dbc.connection.R2dbcTransactionManager;
import org.springframework.r2dbc.core.DatabaseClient;
import org.springframework.transaction.reactive.TransactionalOperator;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;
import org.testcontainers.mysql.MySQLContainer;
import reactor.test.StepVerifier;

import java.sql.DriverManager;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

@Testcontainers
class R2dbcParliamentStagingRepositoryTest {
    @Container
    static final MySQLContainer MYSQL = new MySQLContainer("mysql:8.4")
            .withDatabaseName("parliament")
            .withUsername("parliament")
            .withPassword("test-password");

    private DatabaseClient databaseClient;
    private R2dbcParliamentStagingRepository repository;

    @BeforeEach
    void setUp() throws Exception {
        try (var connection = DriverManager.getConnection(
                MYSQL.getJdbcUrl(), MYSQL.getUsername(), MYSQL.getPassword())) {
            ScriptUtils.executeSqlScript(connection, new ClassPathResource("sql/schema-parliament.sql"));
        }
        String r2dbcUrl = "r2dbc:mysql://" + MYSQL.getUsername() + ":" + MYSQL.getPassword()
                + "@" + MYSQL.getHost() + ":" + MYSQL.getMappedPort(3306)
                + "/" + MYSQL.getDatabaseName();
        var connectionFactory = ConnectionFactories.get(r2dbcUrl);
        databaseClient = DatabaseClient.create(connectionFactory);
        repository = new R2dbcParliamentStagingRepository(
                databaseClient,
                TransactionalOperator.create(new R2dbcTransactionManager(connectionFactory)));
    }

    @Test
    void savesNormalisedPageAndAdvancesCheckpointInOneTransaction() {
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
                "{\"NAAS_CD\":\"A001\"}", List.of(person));

        StepVerifier.create(repository.savePage(source, List.of(record), 1, 2, false)
                        .then(repository.nextPage(source.key())))
                .expectNext(2)
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
    }

    private reactor.core.publisher.Mono<Long> count(String table) {
        return databaseClient.sql("SELECT COUNT(*) AS count_value FROM " + table)
                .map((row, metadata) -> row.get("count_value", Long.class))
                .one();
    }
}
