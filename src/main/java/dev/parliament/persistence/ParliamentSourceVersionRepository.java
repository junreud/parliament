package dev.parliament.persistence;

import dev.parliament.config.ParliamentSourceDefinition;
import dev.parliament.domain.NormalizedParliamentRecord;
import org.springframework.r2dbc.core.DatabaseClient;
import reactor.core.publisher.Mono;

/** Called inside the page transaction so evidence and processing jobs cannot be lost. */
public final class ParliamentSourceVersionRepository {
    private final DatabaseClient database;

    public ParliamentSourceVersionRepository(DatabaseClient database) {
        this.database = database;
    }

    public Mono<Void> archive(ParliamentSourceDefinition source, NormalizedParliamentRecord record) {
        Mono<Void> version = database.sql("""
                INSERT INTO parliament_source_record_version
                  (source_key, record_key, payload_hash, api_code, raw_payload)
                VALUES (:source, :record, :hash, :api, :raw)
                ON DUPLICATE KEY UPDATE payload_hash = payload_hash
                """)
                .bind("source", source.key()).bind("record", record.recordKey())
                .bind("hash", record.payloadHash()).bind("api", source.apiCode())
                .bind("raw", record.rawJson()).fetch().rowsUpdated().then();
        Mono<Void> queue = database.sql("""
                INSERT INTO parliament_processing_outbox (source_key, record_key, payload_hash)
                VALUES (:source, :record, :hash)
                ON DUPLICATE KEY UPDATE payload_hash = payload_hash
                """)
                .bind("source", source.key()).bind("record", record.recordKey())
                .bind("hash", record.payloadHash()).fetch().rowsUpdated().then();
        return version.then(queue);
    }
}
