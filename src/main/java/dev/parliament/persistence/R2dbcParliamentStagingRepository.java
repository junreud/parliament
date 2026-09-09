package dev.parliament.persistence;

import dev.parliament.config.ParliamentSourceDefinition;
import dev.parliament.domain.NormalizedParliamentRecord;
import dev.parliament.domain.PersonCandidate;
import dev.parliament.domain.SocialAccount;
import dev.parliament.domain.SocialPlatform;
import dev.parliament.util.TextUtil;
import org.springframework.r2dbc.core.DatabaseClient;
import org.springframework.transaction.reactive.TransactionalOperator;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;
import dev.parliament.service.IngestionExpectation;
import dev.parliament.service.IngestionRunStatus;
import dev.parliament.service.IngestionSourceOutcome;
import dev.parliament.service.IngestionTrigger;

import java.util.List;
import java.time.Instant;

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
    public Mono<Long> startRun(
            IngestionTrigger trigger,
            Instant scheduledFor,
            Instant startedAt,
            List<IngestionSourceSchedule> sources
    ) {
        DatabaseClient.GenericExecuteSpec runInsert = databaseClient.sql("""
                        INSERT INTO parliament_ingestion_run
                          (trigger_type, scheduled_for, started_at, status, expected_sources)
                        VALUES (:triggerType, :scheduledFor, :startedAt, 'RUNNING', :expectedSources)
                        """)
                .bind("triggerType", trigger.name())
                .bind("startedAt", startedAt)
                .bind("expectedSources", sources.size());
        runInsert = scheduledFor == null
                ? runInsert.bindNull("scheduledFor", Instant.class)
                : runInsert.bind("scheduledFor", scheduledFor);
        Mono<Long> operation = runInsert
                .filter(statement -> statement.returnGeneratedValues("run_id"))
                .map((row, metadata) -> row.get("run_id", Long.class))
                .one()
                .switchIfEmpty(Mono.error(new IllegalStateException("ingestion run id was not generated")))
                .flatMap(runId -> Flux.fromIterable(sources)
                        .concatMap(source -> databaseClient.sql("""
                                        INSERT INTO parliament_ingestion_source_run
                                          (run_id, source_key, api_code, source_name, expectation, outcome)
                                        VALUES (:runId, :sourceKey, :apiCode, :sourceName, :expectation, 'SCHEDULED')
                                        """)
                                .bind("runId", runId)
                                .bind("sourceKey", source.sourceKey())
                                .bind("apiCode", source.apiCode())
                                .bind("sourceName", source.sourceName())
                                .bind("expectation", source.expectation().name())
                                .fetch().rowsUpdated())
                        .then()
                        .thenReturn(runId));
        return transaction.transactional(operation);
    }

    @Override
    public Mono<Void> markSourceRunStarted(long runId, String sourceKey, Instant startedAt) {
        return databaseClient.sql("""
                        UPDATE parliament_ingestion_source_run
                        SET outcome = 'RUNNING', started_at = :startedAt
                        WHERE run_id = :runId AND source_key = :sourceKey
                        """)
                .bind("runId", runId)
                .bind("sourceKey", sourceKey)
                .bind("startedAt", startedAt)
                .fetch().rowsUpdated().then();
    }

    @Override
    public Mono<Void> completeSourceRun(
            long runId,
            String sourceKey,
            IngestionSourceCompletion completion
    ) {
        DatabaseClient.GenericExecuteSpec update = databaseClient.sql("""
                        UPDATE parliament_ingestion_source_run
                        SET outcome = :outcome,
                            finished_at = :finishedAt,
                            variants = :variants,
                            scanned = :scanned,
                            changed_rows = :changed,
                            unchanged_rows = :unchanged,
                            removed_rows = :removed,
                            pages = :pages,
                            error_code = :errorCode,
                            message = :message
                        WHERE run_id = :runId AND source_key = :sourceKey
                        """)
                .bind("outcome", completion.outcome().name())
                .bind("finishedAt", completion.finishedAt())
                .bind("variants", completion.variants())
                .bind("scanned", completion.scanned())
                .bind("changed", completion.changed())
                .bind("unchanged", completion.unchanged())
                .bind("removed", completion.removed())
                .bind("pages", completion.pages())
                .bind("runId", runId)
                .bind("sourceKey", sourceKey);
        update = completion.errorCode() == null
                ? update.bindNull("errorCode", String.class)
                : update.bind("errorCode", completion.errorCode());
        update = completion.message() == null
                ? update.bindNull("message", String.class)
                : update.bind("message", completion.message());
        return update.fetch().rowsUpdated().then();
    }

    @Override
    public Mono<Void> completeRun(
            long runId,
            IngestionRunStatus status,
            Instant finishedAt,
            int succeededSources,
            int failedSources
    ) {
        return databaseClient.sql("""
                        UPDATE parliament_ingestion_run
                        SET status = :status,
                            finished_at = :finishedAt,
                            succeeded_sources = :succeededSources,
                            failed_sources = :failedSources
                        WHERE run_id = :runId
                        """)
                .bind("status", status.name())
                .bind("finishedAt", finishedAt)
                .bind("succeededSources", succeededSources)
                .bind("failedSources", failedSources)
                .bind("runId", runId)
                .fetch().rowsUpdated().then();
    }

    @Override
    public Flux<IngestionHistoryEntry> findHistory(Instant fromInclusive, Instant toExclusive) {
        return databaseClient.sql("""
                        SELECT r.run_id, r.trigger_type, r.scheduled_for,
                               r.started_at AS run_started_at, r.status AS run_status,
                               s.source_key, s.api_code, s.source_name, s.expectation,
                               s.outcome, s.started_at AS source_started_at,
                               s.finished_at AS source_finished_at,
                               s.variants, s.scanned, s.changed_rows, s.unchanged_rows,
                               s.removed_rows, s.pages, s.error_code, s.message
                        FROM parliament_ingestion_run r
                        JOIN parliament_ingestion_source_run s ON s.run_id = r.run_id
                        WHERE COALESCE(r.scheduled_for, r.started_at) >= :fromInclusive
                          AND COALESCE(r.scheduled_for, r.started_at) < :toExclusive
                        ORDER BY COALESCE(r.scheduled_for, r.started_at), r.run_id, s.source_key
                        """)
                .bind("fromInclusive", fromInclusive)
                .bind("toExclusive", toExclusive)
                .map((row, metadata) -> new IngestionHistoryEntry(
                        row.get("run_id", Long.class),
                        IngestionTrigger.valueOf(row.get("trigger_type", String.class)),
                        row.get("scheduled_for", Instant.class),
                        row.get("run_started_at", Instant.class),
                        IngestionRunStatus.valueOf(row.get("run_status", String.class)),
                        row.get("source_key", String.class),
                        row.get("api_code", String.class),
                        row.get("source_name", String.class),
                        IngestionExpectation.valueOf(row.get("expectation", String.class)),
                        IngestionSourceOutcome.valueOf(row.get("outcome", String.class)),
                        row.get("source_started_at", Instant.class),
                        row.get("source_finished_at", Instant.class),
                        number(row.get("variants", Integer.class)),
                        number(row.get("scanned", Integer.class)),
                        number(row.get("changed_rows", Integer.class)),
                        number(row.get("unchanged_rows", Integer.class)),
                        number(row.get("removed_rows", Integer.class)),
                        number(row.get("pages", Integer.class)),
                        row.get("error_code", String.class),
                        row.get("message", String.class)))
                .all();
    }

    private static int number(Integer value) {
        return value == null ? 0 : value;
    }

    @Override
    public Flux<String> distinctRawValues(String sourceKey, String field, int limit) {
        return distinctRawValues(sourceKey, field, null, limit);
    }

    @Override
    public Flux<String> distinctRawValuesChangedSince(
            String sourceKey,
            String field,
            Instant changedSince,
            int limit
    ) {
        if (changedSince == null) {
            return Flux.error(new IllegalArgumentException("changedSince is required"));
        }
        return distinctRawValues(sourceKey, field, changedSince, limit);
    }

    private Flux<String> distinctRawValues(
            String sourceKey,
            String field,
            Instant changedSince,
            int limit
    ) {
        if (sourceKey == null || sourceKey.isBlank()) {
            return Flux.error(new IllegalArgumentException("sourceKey is required"));
        }
        if (field == null || !field.matches("[A-Z0-9_]+")) {
            return Flux.error(new IllegalArgumentException("invalid raw payload field"));
        }
        if (limit < 1 || limit > 100_000) {
            return Flux.error(new IllegalArgumentException("limit must be between 1 and 100000"));
        }
        String jsonPath = "$." + field;
        String changedClause = changedSince == null ? "" : " AND content_changed_at >= :changedSince\n";
        DatabaseClient.GenericExecuteSpec spec = databaseClient.sql("""
                        SELECT JSON_UNQUOTE(JSON_EXTRACT(raw_payload, :jsonPath)) AS parameter_value
                        FROM parliament_source_record
                        WHERE source_key = :sourceKey
                          AND JSON_EXTRACT(raw_payload, :jsonPath) IS NOT NULL
                          AND JSON_UNQUOTE(JSON_EXTRACT(raw_payload, :jsonPath)) <> ''
                        """ + changedClause + """
                        GROUP BY parameter_value
                        ORDER BY MAX(content_changed_at) DESC
                        LIMIT :resultLimit
                        """)
                .bind("jsonPath", jsonPath)
                .bind("sourceKey", sourceKey)
                .bind("resultLimit", limit);
        if (changedSince != null) {
            spec = spec.bind("changedSince", changedSince);
        }
        return spec
                .map((row, metadata) -> row.get("parameter_value", String.class))
                .all();
    }

    @Override
    public Mono<Instant> lastSuccessfulSyncAt(String sourceKey) {
        return databaseClient.sql("""
                        SELECT last_successful_watermark
                        FROM parliament_source_sync_state
                        WHERE source_key = :sourceKey
                        """)
                .bind("sourceKey", sourceKey)
                .map((row, metadata) -> row.get("last_successful_watermark", Instant.class))
                .one();
    }

    @Override
    public Mono<Void> markSourceSyncStarted(String sourceKey, Instant startedAt) {
        return databaseClient.sql("""
                        INSERT INTO parliament_source_sync_state
                          (source_key, status, last_started_at)
                        VALUES (:sourceKey, 'RUNNING', :startedAt)
                        ON DUPLICATE KEY UPDATE
                          status = 'RUNNING', last_started_at = VALUES(last_started_at), last_error_code = NULL
                        """)
                .bind("sourceKey", sourceKey)
                .bind("startedAt", startedAt)
                .fetch().rowsUpdated().then();
    }

    @Override
    public Mono<Void> markSourceSyncCompleted(
            String sourceKey,
            Instant watermark,
            Instant finishedAt
    ) {
        return databaseClient.sql("""
                        UPDATE parliament_source_sync_state
                        SET status = 'COMPLETE',
                            last_successful_watermark = :watermark,
                            last_finished_at = :finishedAt,
                            last_error_code = NULL
                        WHERE source_key = :sourceKey
                        """)
                .bind("sourceKey", sourceKey)
                .bind("watermark", watermark)
                .bind("finishedAt", finishedAt)
                .fetch().rowsUpdated().then();
    }

    @Override
    public Mono<Void> markSourceSyncFailed(
            String sourceKey,
            Instant finishedAt,
            String errorCode
    ) {
        return databaseClient.sql("""
                        UPDATE parliament_source_sync_state
                        SET status = 'FAILED', last_finished_at = :finishedAt, last_error_code = :errorCode
                        WHERE source_key = :sourceKey
                        """)
                .bind("sourceKey", sourceKey)
                .bind("finishedAt", finishedAt)
                .bind("errorCode", errorCode)
                .fetch().rowsUpdated().then();
    }

    @Override
    public Flux<SocialAccountVerificationTarget> findDue(Instant verifiedBefore, int limit) {
        if (verifiedBefore == null) {
            return Flux.error(new IllegalArgumentException("verifiedBefore is required"));
        }
        if (limit < 1 || limit > 10_000) {
            return Flux.error(new IllegalArgumentException("limit must be between 1 and 10000"));
        }
        return databaseClient.sql("""
                        SELECT identity_key, platform, url_hash, canonical_url
                        FROM parliament_social_account
                        WHERE last_url_verified_at IS NULL OR last_url_verified_at < :verifiedBefore
                        ORDER BY COALESCE(last_url_verified_at, TIMESTAMP('1970-01-01')) ASC
                        LIMIT :resultLimit
                        """)
                .bind("verifiedBefore", verifiedBefore)
                .bind("resultLimit", limit)
                .map((row, metadata) -> new SocialAccountVerificationTarget(
                        row.get("identity_key", String.class),
                        SocialPlatform.valueOf(row.get("platform", String.class)),
                        row.get("url_hash", String.class),
                        row.get("canonical_url", String.class)))
                .all();
    }

    @Override
    public Mono<Void> saveVerification(SocialAccountVerification verification) {
        DatabaseClient.GenericExecuteSpec spec = databaseClient.sql("""
                        UPDATE parliament_social_account
                        SET url_verification_status = :status,
                            url_http_status = :httpStatus,
                            resolved_url = :resolvedUrl,
                            url_verification_error = :errorCode,
                            last_url_verified_at = :verifiedAt
                        WHERE identity_key = :identityKey
                          AND platform = :platform
                          AND url_hash = :urlHash
                        """)
                .bind("status", verification.status().name())
                .bind("verifiedAt", verification.verifiedAt())
                .bind("identityKey", verification.target().identityKey())
                .bind("platform", verification.target().platform().name())
                .bind("urlHash", verification.target().urlHash());
        spec = bindNullable(spec, "httpStatus", verification.httpStatus(), Integer.class);
        spec = bindNullable(spec, "resolvedUrl", verification.resolvedUrl(), String.class);
        spec = bindNullable(spec, "errorCode", verification.errorCode(), String.class);
        return spec.fetch().rowsUpdated().then();
    }

    @Override
    public Mono<ParliamentIngestionCheckpoint> checkpoint(String sourceKey, String variantKey) {
        return databaseClient.sql("""
                        SELECT next_page, complete
                        FROM parliament_ingestion_checkpoint
                        WHERE source_key = :sourceKey AND variant_key = :variantKey
                        """)
                .bind("sourceKey", sourceKey)
                .bind("variantKey", variantKey)
                .map((row, metadata) -> new ParliamentIngestionCheckpoint(
                        row.get("next_page", Integer.class),
                        Boolean.TRUE.equals(row.get("complete", Boolean.class))))
                .one();
    }

    @Override
    public Mono<Void> resetCheckpoint(String sourceKey, String variantKey) {
        return databaseClient.sql("""
                        INSERT INTO parliament_ingestion_checkpoint
                          (source_key, variant_key, next_page, complete, last_page, last_success_at)
                        VALUES (:sourceKey, :variantKey, 1, false, NULL, NULL)
                        ON DUPLICATE KEY UPDATE
                          next_page = 1,
                          complete = false,
                          last_page = NULL,
                          last_success_at = NULL
                        """)
                .bind("sourceKey", sourceKey)
                .bind("variantKey", variantKey)
                .fetch().rowsUpdated().then();
    }

    @Override
    public Mono<Void> savePage(
            ParliamentSourceDefinition source,
            List<NormalizedParliamentRecord> records,
            int currentPage,
            int nextPage,
            boolean complete
    ) {
        Mono<Void> work = Flux.fromIterable(records)
                .concatMap(record -> saveRecord(source, record))
                .then(saveCheckpoint(source.key(), source.variantKey(), currentPage, nextPage, complete))
                .then();
        return transaction.transactional(work);
    }

    @Override
    public Mono<ParliamentPageWriteResult> saveChangedPage(
            ParliamentSourceDefinition source,
            List<NormalizedParliamentRecord> records,
            int currentPage,
            int nextPage,
            boolean complete
    ) {
        Mono<ParliamentPageWriteResult> work = Flux.fromIterable(records)
                .concatMap(record -> payloadHash(source.key(), record.recordKey())
                        .map(record.payloadHash()::equals)
                        .defaultIfEmpty(false)
                        .flatMap(unchanged -> unchanged
                                ? touchRecord(source.key(), record.recordKey()).thenReturn(false)
                                : saveRecord(source, record).thenReturn(true)))
                .collectList()
                .flatMap(changes -> saveCheckpoint(
                                source.key(), source.variantKey(), currentPage, nextPage, complete)
                        .thenReturn(new ParliamentPageWriteResult(
                                records.size(),
                                (int) changes.stream().filter(Boolean::booleanValue).count(),
                                (int) changes.stream().filter(changed -> !changed).count())));
        return transaction.transactional(work);
    }

    private Mono<String> payloadHash(String sourceKey, String recordKey) {
        return databaseClient.sql("""
                        SELECT payload_hash
                        FROM parliament_source_record
                        WHERE source_key = :sourceKey AND record_key = :recordKey
                        """)
                .bind("sourceKey", sourceKey)
                .bind("recordKey", recordKey)
                .map((row, metadata) -> row.get("payload_hash", String.class))
                .one();
    }

    private Mono<Void> touchRecord(String sourceKey, String recordKey) {
        return databaseClient.sql("""
                        UPDATE parliament_source_record
                        SET last_seen_at = CURRENT_TIMESTAMP(6)
                        WHERE source_key = :sourceKey AND record_key = :recordKey
                        """)
                .bind("sourceKey", sourceKey)
                .bind("recordKey", recordKey)
                .fetch().rowsUpdated().then();
    }

    @Override
    public Mono<Integer> finalizeSourceSnapshot(String sourceKey, Instant observedSince) {
        Mono<Void> clearStaleSocialEvidence = "negnlnyvatsjwocar".equals(sourceKey)
                ? databaseClient.sql("""
                                UPDATE parliament_social_account social
                                SET verification_status = 'UNVERIFIED',
                                    official_evidence_source_key = NULL,
                                    is_primary = false
                                WHERE official_evidence_source_key = :sourceKey
                                  AND EXISTS (
                                    SELECT 1
                                    FROM parliament_record_person link
                                    JOIN parliament_source_record record
                                      ON record.source_key = link.source_key
                                     AND record.record_key = link.record_key
                                    WHERE link.identity_key = social.identity_key
                                      AND record.source_key = :sourceKey
                                      AND record.last_seen_at < :observedSince
                                  )
                                  AND NOT EXISTS (
                                    SELECT 1
                                    FROM parliament_record_person link
                                    JOIN parliament_source_record record
                                      ON record.source_key = link.source_key
                                     AND record.record_key = link.record_key
                                    WHERE link.identity_key = social.identity_key
                                      AND record.source_key = :sourceKey
                                      AND record.last_seen_at >= :observedSince
                                  )
                                """)
                        .bind("sourceKey", sourceKey)
                        .bind("observedSince", observedSince)
                        .fetch().rowsUpdated().then()
                : Mono.empty();
        Mono<Void> deletePositions = databaseClient.sql("""
                        DELETE position
                        FROM parliament_person_position position
                        JOIN parliament_source_record record
                          ON record.source_key = position.source_key
                         AND record.record_key = position.source_record_key
                        WHERE record.source_key = :sourceKey
                          AND record.last_seen_at < :observedSince
                        """)
                .bind("sourceKey", sourceKey)
                .bind("observedSince", observedSince)
                .fetch().rowsUpdated().then();
        Mono<Void> deleteLinks = databaseClient.sql("""
                        DELETE link
                        FROM parliament_record_person link
                        JOIN parliament_source_record record
                          ON record.source_key = link.source_key
                         AND record.record_key = link.record_key
                        WHERE record.source_key = :sourceKey
                          AND record.last_seen_at < :observedSince
                        """)
                .bind("sourceKey", sourceKey)
                .bind("observedSince", observedSince)
                .fetch().rowsUpdated().then();
        Mono<Integer> deleteRecords = databaseClient.sql("""
                        DELETE FROM parliament_source_record
                        WHERE source_key = :sourceKey AND last_seen_at < :observedSince
                        """)
                .bind("sourceKey", sourceKey)
                .bind("observedSince", observedSince)
                .fetch().rowsUpdated().map(Long::intValue);
        Mono<Integer> work = clearStaleSocialEvidence
                .then(deletePositions)
                .then(deleteLinks)
                .then(deleteRecords)
                .flatMap(removed -> "nwvrqwxyaytdsfvhu".equals(sourceKey)
                        ? rebuildLegislatorClassification().thenReturn(removed)
                        : Mono.just(removed));
        return transaction.transactional(work);
    }

    private Mono<Void> rebuildLegislatorClassification() {
        return execute("DELETE FROM parliament_legislator_status")
                .then(execute("DELETE FROM parliament_legislator_term"))
                .then(execute("""
                        INSERT IGNORE INTO parliament_legislator_term
                          (identity_key, assembly_term, term_label, evidence_source_key, evidence_record_key)
                        SELECT identifier.identity_key,
                          CASE WHEN terms.term_label = '제헌' THEN 1
                               ELSE CAST(REGEXP_REPLACE(terms.term_label, '[^0-9]', '') AS UNSIGNED) END,
                          terms.term_label, record.source_key, record.record_key
                        FROM parliament_source_record record
                        JOIN parliament_person_identifier identifier
                          ON identifier.identifier_namespace = 'OPEN_ASSEMBLY_MEMBER'
                         AND identifier.external_id = JSON_UNQUOTE(JSON_EXTRACT(record.raw_payload, '$.NAAS_CD'))
                        JOIN JSON_TABLE(
                          CONCAT('["', REPLACE(REPLACE(
                            JSON_UNQUOTE(JSON_EXTRACT(record.raw_payload, '$.GTELT_ERACO')), ' ', ''),
                            ',', '","'), '"]'),
                          '$[*]' COLUMNS (term_label varchar(32) PATH '$')) terms
                        WHERE record.source_key = 'allnamember'
                          AND JSON_UNQUOTE(JSON_EXTRACT(record.raw_payload, '$.GTELT_ERACO')) IS NOT NULL
                          AND JSON_UNQUOTE(JSON_EXTRACT(record.raw_payload, '$.GTELT_ERACO')) <> ''
                          AND (terms.term_label = '제헌'
                               OR REGEXP_REPLACE(terms.term_label, '[^0-9]', '') <> '')
                        """))
                .then(execute("""
                        INSERT IGNORE INTO parliament_legislator_term
                          (identity_key, assembly_term, term_label, evidence_source_key, evidence_record_key)
                        SELECT identifier.identity_key,
                          CAST(REGEXP_REPLACE(terms.term_label, '[^0-9]', '') AS UNSIGNED),
                          terms.term_label, record.source_key, record.record_key
                        FROM parliament_source_record record
                        JOIN parliament_person_identifier identifier
                          ON identifier.identifier_namespace = 'OPEN_ASSEMBLY_MEMBER'
                         AND identifier.external_id = JSON_UNQUOTE(JSON_EXTRACT(record.raw_payload, '$.MONA_CD'))
                        JOIN JSON_TABLE(
                          CONCAT('["', REPLACE(REPLACE(
                            JSON_UNQUOTE(JSON_EXTRACT(record.raw_payload, '$.UNITS')), ' ', ''),
                            ',', '","'), '"]'),
                          '$[*]' COLUMNS (term_label varchar(32) PATH '$')) terms
                        WHERE record.source_key = 'nwvrqwxyaytdsfvhu'
                          AND JSON_UNQUOTE(JSON_EXTRACT(record.raw_payload, '$.UNITS')) IS NOT NULL
                          AND JSON_UNQUOTE(JSON_EXTRACT(record.raw_payload, '$.UNITS')) <> ''
                          AND REGEXP_REPLACE(terms.term_label, '[^0-9]', '') <> ''
                        """))
                .then(execute("""
                        INSERT INTO parliament_legislator_status
                          (identity_key, membership_status, current_assembly_term, latest_assembly_term,
                           evidence_source_key, evidence_record_key)
                        SELECT person.identity_key, 'FORMER', NULL, MAX(term.assembly_term),
                               'allnamember', NULL
                        FROM parliament_person person
                        LEFT JOIN parliament_legislator_term term
                          ON term.identity_key = person.identity_key
                        WHERE person.person_kind = 'LEGISLATOR'
                        GROUP BY person.identity_key
                        """))
                .then(execute("""
                        INSERT INTO parliament_legislator_status
                          (identity_key, membership_status, current_assembly_term, latest_assembly_term,
                           evidence_source_key, evidence_record_key)
                        SELECT identifier.identity_key, 'CURRENT', MAX(term.assembly_term),
                               MAX(term.assembly_term), record.source_key, record.record_key
                        FROM parliament_source_record record
                        JOIN parliament_person_identifier identifier
                          ON identifier.identifier_namespace = 'OPEN_ASSEMBLY_MEMBER'
                         AND identifier.external_id = JSON_UNQUOTE(JSON_EXTRACT(record.raw_payload, '$.MONA_CD'))
                        LEFT JOIN parliament_legislator_term term
                          ON term.identity_key = identifier.identity_key
                        WHERE record.source_key = 'nwvrqwxyaytdsfvhu'
                        GROUP BY identifier.identity_key, record.source_key, record.record_key
                        ON DUPLICATE KEY UPDATE
                          membership_status = VALUES(membership_status),
                          current_assembly_term = VALUES(current_assembly_term),
                          latest_assembly_term = VALUES(latest_assembly_term),
                          evidence_source_key = VALUES(evidence_source_key),
                          evidence_record_key = VALUES(evidence_record_key),
                          classified_at = CURRENT_TIMESTAMP(6)
                        """));
    }

    private Mono<Void> execute(String sql) {
        return databaseClient.sql(sql).fetch().rowsUpdated().then();
    }

    private Mono<Void> saveRecord(ParliamentSourceDefinition source, NormalizedParliamentRecord record) {
        DatabaseClient.GenericExecuteSpec recordInsert = databaseClient.sql("""
                        INSERT INTO parliament_source_record
                          (source_key, record_key, api_code, data_go_kr_id, payload_hash, raw_payload)
                        VALUES
                          (:sourceKey, :recordKey, :apiCode, :dataGoKrId, :payloadHash, :rawPayload)
                        ON DUPLICATE KEY UPDATE
                          content_changed_at = CASE
                            WHEN payload_hash <> VALUES(payload_hash) THEN CURRENT_TIMESTAMP(6)
                            ELSE content_changed_at
                          END,
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
                .concatMap(account -> saveSocial(source.key(), person.identityKey(), account))
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

    private Mono<Void> saveSocial(String sourceKey, String identityKey, SocialAccount account) {
        String urlHash = TextUtil.textSha1(account.url());
        Mono<Void> clearPreviousPrimary = databaseClient.sql("""
                        UPDATE parliament_social_account
                        SET is_primary = false
                        WHERE identity_key = :identityKey
                          AND platform = :platform
                          AND url_hash <> :urlHash
                        """)
                .bind("identityKey", identityKey)
                .bind("platform", account.platform().name())
                .bind("urlHash", urlHash)
                .fetch().rowsUpdated().then();
        DatabaseClient.GenericExecuteSpec spec = databaseClient.sql("""
                        INSERT INTO parliament_social_account
                          (identity_key, platform, url_hash, canonical_url, handle, is_primary,
                           verification_status, official_evidence_source_key)
                        VALUES (:identityKey, :platform, :urlHash, :url, :handle, :isPrimary,
                                :verificationStatus, :officialEvidenceSourceKey)
                        ON DUPLICATE KEY UPDATE
                          handle = VALUES(handle),
                          is_primary = VALUES(is_primary),
                          verification_status = CASE
                            WHEN VALUES(verification_status) = 'OFFICIAL_DIRECTORY'
                              THEN VALUES(verification_status)
                            ELSE verification_status
                          END,
                          official_evidence_source_key = COALESCE(
                            VALUES(official_evidence_source_key), official_evidence_source_key),
                          last_seen_at = CURRENT_TIMESTAMP(6)
                        """)
                .bind("identityKey", identityKey)
                .bind("platform", account.platform().name())
                .bind("urlHash", urlHash)
                .bind("url", account.url())
                .bind("isPrimary", account.primary())
                .bind("verificationStatus", account.verificationStatus().name());
        spec = bindNullable(spec, "handle", account.handle(), String.class);
        String evidenceSource = account.verificationStatus()
                == dev.parliament.domain.SocialVerificationStatus.OFFICIAL_DIRECTORY
                ? sourceKey : null;
        spec = bindNullable(spec, "officialEvidenceSourceKey", evidenceSource, String.class);
        return clearPreviousPrimary.then(spec.fetch().rowsUpdated()).then();
    }

    private Mono<Long> saveCheckpoint(
            String sourceKey,
            String variantKey,
            int currentPage,
            int nextPage,
            boolean complete
    ) {
        return databaseClient.sql("""
                        INSERT INTO parliament_ingestion_checkpoint
                          (source_key, variant_key, next_page, complete, last_page, last_success_at)
                        VALUES (:sourceKey, :variantKey, :nextPage, :complete, :currentPage, CURRENT_TIMESTAMP(6))
                        ON DUPLICATE KEY UPDATE
                          next_page = VALUES(next_page),
                          complete = VALUES(complete),
                          last_page = VALUES(last_page),
                          last_success_at = VALUES(last_success_at)
                        """)
                .bind("sourceKey", sourceKey)
                .bind("variantKey", variantKey)
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
