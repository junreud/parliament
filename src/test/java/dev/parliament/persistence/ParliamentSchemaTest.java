package dev.parliament.persistence;

import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.nio.charset.StandardCharsets;

import static org.assertj.core.api.Assertions.assertThat;

class ParliamentSchemaTest {

    @Test
    void schemaContainsNormalisedPeopleSocialRecordsAndCheckpoints() throws IOException {
        try (var input = getClass().getResourceAsStream("/sql/schema-parliament.sql")) {
            assertThat(input).isNotNull();
            String sql = new String(input.readAllBytes(), StandardCharsets.UTF_8);
            assertThat(sql).contains(
                    "CREATE TABLE `parliament_person`",
                    "CREATE TABLE `parliament_legislator_term`",
                    "CREATE TABLE `parliament_legislator_status`",
                    "CREATE TABLE `parliament_person_position`",
                    "CREATE TABLE `parliament_social_account`",
                    "CREATE TABLE `parliament_source_record`",
                    "CREATE TABLE `parliament_record_person`",
                    "CREATE TABLE `parliament_ingestion_checkpoint`",
                    "CREATE TABLE `parliament_source_sync_state`",
                    "CREATE TABLE `parliament_ingestion_run`",
                    "CREATE TABLE `parliament_ingestion_source_run`");
            assertThat(sql).contains(
                    "CREATE VIEW `parliament_current_legislator`",
                    "CREATE VIEW `parliament_former_legislator`");
            assertThat(sql).contains("`raw_payload` json NOT NULL");
            assertThat(sql).contains("`content_changed_at` timestamp(6)");
            assertThat(sql).doesNotContain("api_key", "service_key", "password");
        }
    }
}
