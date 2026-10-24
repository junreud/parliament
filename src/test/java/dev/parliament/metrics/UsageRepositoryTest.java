package dev.parliament.metrics;

import io.r2dbc.spi.ConnectionFactories;
import org.junit.jupiter.api.Test;
import org.springframework.core.io.ClassPathResource;
import org.springframework.jdbc.datasource.init.ScriptUtils;
import org.springframework.r2dbc.core.DatabaseClient;
import dev.parliament.support.TestDatabase;
import reactor.test.StepVerifier;

import java.sql.DriverManager;
import java.time.Instant;
import static org.assertj.core.api.Assertions.assertThat;

class UsageRepositoryTest {
    @Test
    void measuresOnlyActivatedMatureCohortsAndReportsUnknownWhenNoDenominator() throws Exception {
        try (TestDatabase mysql = TestDatabase.start("metrics")) {
            try (var connection = DriverManager.getConnection(mysql.jdbcUrl(), mysql.username(), mysql.password())) {
                connection.createStatement().execute("DROP TABLE IF EXISTS tracking_usage_event");
                ScriptUtils.executeSqlScript(connection, new ClassPathResource("sql/schema-metrics.sql"));
            }
            DatabaseClient database = DatabaseClient.create(ConnectionFactories.get(mysql.r2dbcUrl()));
            UsageRepository repository = new UsageRepository(database);
            Instant start = Instant.parse("2026-09-01T00:00:00Z");
            Instant end = Instant.parse("2026-10-08T00:00:00Z");
            StepVerifier.create(repository.report(start, end, end))
                    .assertNext(report -> { assertThat(report.activated()).isZero(); assertThat(report.week4Retention()).isNull(); })
                    .verifyComplete();
            repository.record("user-1", "follow_saved", null, start).block();
            repository.record("user-1", "activity_opened", null, start.plusSeconds(1)).block();
            repository.record("user-1", "activity_opened", null, start.plusSeconds(22 * 86400)).block();
            repository.record("user-1", "relevance", true, start).block();
            repository.record("user-2", "follow_saved", null, start).block();
            repository.record("user-2", "activity_opened", null, start.plusSeconds(1)).block();
            repository.record("new-user", "follow_saved", null, end.minusSeconds(100)).block();
            repository.record("new-user", "activity_opened", null, end.minusSeconds(50)).block();
            StepVerifier.create(repository.report(start, end, end))
                    .assertNext(report -> {
                        assertThat(report.activated()).isEqualTo(3);
                        assertThat(report.week4Eligible()).isEqualTo(2);
                        assertThat(report.week4Returned()).isEqualTo(1);
                        assertThat(report.week4Retention()).isEqualTo(0.5);
                        assertThat(report.relevanceResponses()).isEqualTo(1);
                        assertThat(report.relevancePositive()).isEqualTo(1);
                    }).verifyComplete();
        }
    }
}
