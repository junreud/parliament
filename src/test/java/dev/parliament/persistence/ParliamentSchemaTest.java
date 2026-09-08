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
                    "CREATE TABLE `parliament_person_position`",
                    "CREATE TABLE `parliament_social_account`",
                    "CREATE TABLE `parliament_source_record`",
                    "CREATE TABLE `parliament_record_person`",
                    "CREATE TABLE `parliament_ingestion_checkpoint`");
            assertThat(sql).contains("`raw_payload` json NOT NULL");
            assertThat(sql).doesNotContain("api_key", "service_key", "password");
        }
    }
}

