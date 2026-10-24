package dev.parliament.knowledge;

import static org.assertj.core.api.Assertions.*;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import dev.parliament.support.TestDatabase;
import io.r2dbc.spi.ConnectionFactories;
import io.r2dbc.spi.ConnectionFactoryOptions;
import java.sql.DriverManager;
import java.time.Instant;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.springframework.core.io.ClassPathResource;
import org.springframework.jdbc.datasource.init.ScriptUtils;
import org.springframework.r2dbc.core.DatabaseClient;

class PublicLawRepositoryTest {
    @Test void onlyPublishedRightsApprovedMetadataIsVisibleAndLaterRestrictionHidesOldApproval() throws Exception {
        // A separate disposable schema/container; never reset the development database.
        try (var mysql = TestDatabase.start("law_public")) {
            try (var connection = DriverManager.getConnection(mysql.jdbcUrl(), mysql.username(), mysql.password())) {
                for (var script : List.of("sql/schema-parliament.sql", "sql/schema-tracking.sql", "sql/schema-knowledge.sql"))
                    ScriptUtils.executeSqlScript(connection, new ClassPathResource(script));
            }
            var factory = ConnectionFactories.get(ConnectionFactoryOptions.parse(mysql.r2dbcUrl()).mutate()
                    .option(ConnectionFactoryOptions.USER, mysql.username())
                    .option(ConnectionFactoryOptions.PASSWORD, mysql.password()).build());
            var db = DatabaseClient.create(factory);
            var mapper = new ObjectMapper().registerModule(new JavaTimeModule());
            var json = new KnowledgeJson(mapper);
            var reads = new PublicLaws(db, mapper);
            var document = PublicLawsTest.law("allowed", "20260910", "013103:286729");
            insert(db, json, "draft_metadata", "draft", document, 0);
            assertThat(reads.list().block().items()).isEmpty();
            insert(db, json, "approved_metadata", "published", document, 1);
            var page = reads.list().block();
            assertThat(page.items()).hasSize(1);
            assertThat(json.write(page)).doesNotContain("rawStorageKey", "private/raw.json", "DRF/", "OC=");
            insert(db, json, "restricted_metadata", "published",
                    PublicLawsTest.law("restricted", "20260910", "013103:286729"), 2);
            assertThat(reads.list().block().items()).isEmpty();
        }
    }

    private void insert(DatabaseClient db, KnowledgeJson json, String id, String state,
                        KnowledgeBatch.Document document, int minute) {
        var batch = new KnowledgeBatch(id, "law-test", List.of(), List.of(document), List.of(), List.of(), List.of(), List.of());
        var payload = json.write(batch);
        db.sql("INSERT INTO knowledge_batch(batch_id,issue_id,payload_hash,payload,review_state,reviewed_at) VALUES(:id,'law-test',:hash,:payload,:state,:at)")
                .bind("id", id).bind("hash", KnowledgeJson.hash(payload)).bind("payload", payload)
                .bind("state", state).bind("at", Instant.parse("2026-10-09T09:00:00Z").plusSeconds(minute * 60L))
                .fetch().rowsUpdated().block();
    }
}
