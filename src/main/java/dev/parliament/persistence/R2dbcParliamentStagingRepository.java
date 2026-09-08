package dev.parliament.persistence;

import dev.parliament.config.ParliamentSourceDefinition;
import dev.parliament.domain.NormalizedParliamentRecord;
import dev.parliament.domain.PersonCandidate;
import dev.parliament.domain.SocialAccount;
import dev.parliament.util.TextUtil;
import org.springframework.r2dbc.core.DatabaseClient;
import org.springframework.transaction.reactive.TransactionalOperator;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;

import java.util.List;

public class R2dbcParliamentStagingRepository implements ParliamentStagingRepository {
    private final DatabaseClient databaseClient;
    private final TransactionalOperator transaction;

    public R2dbcParliamentStagingRepository(
            DatabaseClient databaseClient,
            TransactionalOperator transaction
    ) {
        this.databaseClient = databaseClient;
        this.transaction = transaction;
    }

    @Override
    public Mono<Integer> nextPage(String sourceKey) {
        return databaseClient.sql("""
                        SELECT next_page
                        FROM parliament_ingestion_checkpoint
                        WHERE source_key = :sourceKey AND complete = false
                        """)
                .bind("sourceKey", sourceKey)
                .map((row, metadata) -> row.get("next_page", Integer.class))
                .one();
    }

    @Override
    public Mono<Void> savePage(
            ParliamentSourceDefinition source,
            List<NormalizedParliamentRecord> records,
            int currentPage,
            int nextPage,
            Boolean complete
    ) {
        Mono<Void> work = Flux.fromIterable(records)
                .concatMap(record -> saveRecord(source, record))
                .then(saveCheckpoint(source.key(), currentPage, nextPage, Boolean.TRUE.equals(complete)))
                .then();
        return transaction.transactional(work);
    }

    private Mono<Void> saveRecord(ParliamentSourceDefinition source, NormalizedParliamentRecord record) {
        DatabaseClient.GenericExecuteSpec recordInsert = databaseClient.sql("""
                        INSERT INTO parliament_source_record
                          (source_key, record_key, api_code, data_go_kr_id, payload_hash, raw_payload)
                        VALUES
                          (:sourceKey, :recordKey, :apiCode, :dataGoKrId, :payloadHash, :rawPayload)
                        ON DUPLICATE KEY UPDATE
                          payload_hash = VALUES(payload_hash),
                          raw_payload = VALUES(raw_payload),
                          last_seen_at = CURRENT_TIMESTAMP(6)
                        """)
                .bind("sourceKey", source.key())
                .bind("recordKey", record.recordKey())
                .bind("apiCode", source.apiCode())
                .bind("payloadHash", record.payloadHash())
                .bind("rawPayload", record.rawJson());
        recordInsert = bindNullable(recordInsert, "dataGoKrId", source.dataGoKrId(), String.class);

        return recordInsert.fetch().rowsUpdated()
                .thenMany(Flux.fromIterable(record.people())
                        .concatMap(person -> savePerson(source, record, person)))
                .then();
    }

    private Mono<Void> savePerson(
            ParliamentSourceDefinition source,
            NormalizedParliamentRecord record,
            PersonCandidate person
    ) {
        Mono<Void> personWrite = databaseClient.sql("""
                        INSERT INTO parliament_person
                          (identity_key, canonical_name, person_kind, resolution_status)
                        VALUES (:identityKey, :name, :kind, :resolutionStatus)
                        ON DUPLICATE KEY UPDATE
                          canonical_name = VALUES(canonical_name),
                          person_kind = VALUES(person_kind),
                          resolution_status = VALUES(resolution_status),
                          last_seen_at = CURRENT_TIMESTAMP(6)
                        """)
                .bind("identityKey", person.identityKey())
                .bind("name", person.canonicalName())
                .bind("kind", person.kind().name())
                .bind("resolutionStatus", person.resolutionStatus().name())
                .fetch().rowsUpdated().then();

        Mono<Void> identifierWrite = person.sourcePersonId() == null
                ? Mono.empty()
                : databaseClient.sql("""
                                INSERT INTO parliament_person_identifier
                                  (identifier_namespace, external_id, identity_key)
                                VALUES ('OPEN_ASSEMBLY_MEMBER', :externalId, :identityKey)
                                ON DUPLICATE KEY UPDATE identity_key = VALUES(identity_key)
                                """)
                        .bind("externalId", person.sourcePersonId())
                        .bind("identityKey", person.identityKey())
                        .fetch().rowsUpdated().then();

        Mono<Void> positionWrite = savePosition(source, record, person);
        Mono<Void> socialWrites = Flux.fromIterable(person.socialAccounts())
                .concatMap(account -> saveSocial(person.identityKey(), account))
                .then();
        Mono<Void> linkWrite = databaseClient.sql("""
                        INSERT IGNORE INTO parliament_record_person
                          (source_key, record_key, identity_key)
                        VALUES (:sourceKey, :recordKey, :identityKey)
                        """)
                .bind("sourceKey", source.key())
                .bind("recordKey", record.recordKey())
                .bind("identityKey", person.identityKey())
                .fetch().rowsUpdated().then();

        return personWrite.then(identifierWrite).then(positionWrite).then(socialWrites).then(linkWrite);
    }

    private Mono<Void> savePosition(
            ParliamentSourceDefinition source,
            NormalizedParliamentRecord record,
            PersonCandidate person
    ) {
        if (person.positionTitle() == null && person.organization() == null) {
            return Mono.empty();
        }
        String positionKey = TextUtil.textSha1(String.join("|",
                person.identityKey(), value(person.positionTitle()), value(person.organization()),
                source.key(), record.recordKey()));
        DatabaseClient.GenericExecuteSpec spec = databaseClient.sql("""
                        INSERT IGNORE INTO parliament_person_position
                          (position_key, identity_key, position_title, organization, source_key, source_record_key)
                        VALUES (:positionKey, :identityKey, :positionTitle, :organization, :sourceKey, :recordKey)
                        """)
                .bind("positionKey", positionKey)
                .bind("identityKey", person.identityKey())
                .bind("sourceKey", source.key())
                .bind("recordKey", record.recordKey());
        spec = bindNullable(spec, "positionTitle", person.positionTitle(), String.class);
        spec = bindNullable(spec, "organization", person.organization(), String.class);
        return spec.fetch().rowsUpdated().then();
    }

    private Mono<Void> saveSocial(String identityKey, SocialAccount account) {
        DatabaseClient.GenericExecuteSpec spec = databaseClient.sql("""
                        INSERT INTO parliament_social_account
                          (identity_key, platform, url_hash, canonical_url, handle, is_primary, verification_status)
                        VALUES (:identityKey, :platform, :urlHash, :url, :handle, :isPrimary, :verificationStatus)
                        ON DUPLICATE KEY UPDATE
                          handle = VALUES(handle),
                          is_primary = VALUES(is_primary),
                          verification_status = VALUES(verification_status),
                          last_seen_at = CURRENT_TIMESTAMP(6)
                        """)
                .bind("identityKey", identityKey)
                .bind("platform", account.platform().name())
                .bind("urlHash", TextUtil.textSha1(account.url()))
                .bind("url", account.url())
                .bind("isPrimary", account.primary())
                .bind("verificationStatus", account.verificationStatus().name());
        spec = bindNullable(spec, "handle", account.handle(), String.class);
        return spec.fetch().rowsUpdated().then();
    }

    private Mono<Long> saveCheckpoint(String sourceKey, int currentPage, int nextPage, boolean complete) {
        return databaseClient.sql("""
                        INSERT INTO parliament_ingestion_checkpoint
                          (source_key, next_page, complete, last_page, last_success_at)
                        VALUES (:sourceKey, :nextPage, :complete, :currentPage, CURRENT_TIMESTAMP(6))
                        ON DUPLICATE KEY UPDATE
                          next_page = VALUES(next_page),
                          complete = VALUES(complete),
                          last_page = VALUES(last_page),
                          last_success_at = VALUES(last_success_at)
                        """)
                .bind("sourceKey", sourceKey)
                .bind("nextPage", nextPage)
                .bind("complete", complete)
                .bind("currentPage", currentPage)
                .fetch().rowsUpdated();
    }

    private <T> DatabaseClient.GenericExecuteSpec bindNullable(
            DatabaseClient.GenericExecuteSpec spec,
            String name,
            T value,
            Class<T> type
    ) {
        return value == null ? spec.bindNull(name, type) : spec.bind(name, value);
    }

    private String value(String nullable) {
        return nullable == null ? "" : nullable;
    }
}
