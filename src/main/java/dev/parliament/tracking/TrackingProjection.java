package dev.parliament.tracking;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

import org.springframework.r2dbc.core.DatabaseClient;

import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;

import java.time.Instant;
import java.time.LocalDate;
import java.time.ZoneId;
import java.time.format.DateTimeParseException;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;

/** Projection requires an operator-verified source contract; there is no guessed default. */
public final class TrackingProjection {
    public record Contract(
            String sourceKey,
            String kind,
            boolean verifiedContract,
            Map<String, String> fields,
            Map<String, String> stageMap,
            Map<String, String> voteMap,
            String personNamespace,
            List<String> topics,
            int limit,
            String cursor) {
        public Contract(
                String sourceKey,
                String kind,
                boolean verifiedContract,
                Map<String, String> fields,
                Map<String, String> stageMap,
                Map<String, String> voteMap,
                String personNamespace,
                List<String> topics,
                int limit) {
            this(
                    sourceKey,
                    kind,
                    verifiedContract,
                    fields,
                    stageMap,
                    voteMap,
                    personNamespace,
                    topics,
                    limit,
                    null);
        }
    }

    public record Result(int imported, int skipped, List<String> notes, String nextCursor) {
        public Result(int imported, int skipped, List<String> notes) {
            this(imported, skipped, notes, null);
        }
    }

    public record PersonRef(String id, String name) {}

    private record SourceRow(String recordKey, String hash, String raw, Instant collected) {}

    private final DatabaseClient db;
    private final TrackingRepository repository;
    private final ObjectMapper mapper;
    private final dev.parliament.knowledge.KnowledgeIdentity identities;

    public TrackingProjection(
            DatabaseClient db, TrackingRepository repository, ObjectMapper mapper) {
        this(db,repository,mapper,new dev.parliament.knowledge.KnowledgeIdentity(db,false));
    }
    public TrackingProjection(DatabaseClient db, TrackingRepository repository, ObjectMapper mapper,dev.parliament.knowledge.KnowledgeIdentity identities) {
        this.db = db;
        this.repository = repository;
        this.mapper = mapper;
        this.identities = identities;
    }

    public Mono<Result> project(Contract contract) {
        return identities.refresh().then(Mono.defer(()->projectRecords(contract)));
    }
    private Mono<Result> projectRecords(Contract contract) {
        validateContract(contract);
        if ("vote".equals(contract.kind()))
            return new TrackingVoteProjection(db, repository, mapper,identities).project(contract);
        var cursor =
                contract.cursor() == null
                        ? null
                        : TrackingProjectionCursor.decode(
                                contract.cursor(), contract.sourceKey(), contract.kind());
        String after = cursor == null ? "" : cursor.record();
        AtomicInteger imported = new AtomicInteger(), skipped = new AtomicInteger();
        java.util.Set<String> reasons = new java.util.TreeSet<>();
        return db.sql(
                        "SELECT record_key,payload_hash,raw_payload,content_changed_at FROM"
                                + " parliament_source_record WHERE source_key=:source AND"
                                + " record_key>:after ORDER BY record_key LIMIT :limit")
                .bind("source", contract.sourceKey())
                .bind("after", after)
                .bind("limit", contract.limit() + 1)
                .map(
                        (row, metadata) ->
                                new SourceRow(
                                        row.get("record_key", String.class),
                                        row.get("payload_hash", String.class),
                                        row.get("raw_payload", String.class),
                                        row.get("content_changed_at", Instant.class)))
                .all()
                .collectList()
                .flatMap(
                        rows -> {
                            boolean more = rows.size() > contract.limit();
                            List<SourceRow> page = more ? rows.subList(0, contract.limit()) : rows;
                            String next =
                                    more
                                            ? new TrackingProjectionCursor(
                                                            contract.sourceKey(),
                                                            contract.kind(),
                                                            page.get(page.size() - 1).recordKey(),
                                                            null,
                                                            null)
                                                    .encode()
                                            : null;
                            return Flux.fromIterable(page)
                                    .concatMap(
                                            row ->
                                                    importRow(contract, row)
                                                            .doOnNext(
                                                                    result ->
                                                                            imported
                                                                                    .incrementAndGet())
                                                            .onErrorResume(
                                                                    IllegalArgumentException.class,
                                                                    error -> {
                                                                        skipped.incrementAndGet();
                                                                        if (reasons.size() < 10)
                                                                            reasons.add(
                                                                                    error
                                                                                            .getMessage());
                                                                        return Mono.empty();
                                                                    }))
                                    .then(
                                            Mono.fromSupplier(
                                                    () ->
                                                            new Result(
                                                                    imported.get(),
                                                                    skipped.get(),
                                                                    projectionNotes(reasons),
                                                                    next)));
                        });
    }

    private Mono<TrackingRepository.ImportResult> importRow(Contract contract, SourceRow row) {
        return Mono.defer(
                () -> {
                    JsonNode raw = readRaw(row.raw());
                    return people(contract, row.recordKey(), raw)
                            .flatMap(
                                    refs ->
                                            repository.importDraft(
                                                    toActivity(
                                                            contract,
                                                            row.recordKey(),
                                                            row.hash(),
                                                            raw,
                                                            row.collected(),
                                                            refs)));
                });
    }

    private static List<String> projectionNotes(java.util.Set<String> reasons) {
        return java.util.stream.Stream.concat(
                        java.util.stream.Stream.of(
                                "초안으로 적재했습니다. 공개에는 검수가 필요합니다.", "필수 필드가 없으면 사건 시각을 추측하지 않고 건너뜁니다."),
                        reasons.stream())
                .toList();
    }

    private Mono<List<PersonRef>> people(Contract contract, String recordKey, JsonNode raw) {
        return db.sql(
                                "SELECT " + identities.personSql() + """
                 AS public_id,p.canonical_name
                FROM parliament_record_person r JOIN parliament_person p ON p.identity_key=r.identity_key
                WHERE r.source_key=:source AND r.record_key=:record ORDER BY p.identity_key
                """)
                .bind("source", contract.sourceKey())
                .bind("record", recordKey)
                .map(
                        (row, meta) ->
                                new PersonRef(
                                        row.get("public_id", String.class),
                                        row.get("canonical_name", String.class)))
                .all()
                .collectList();
    }

    private JsonNode readRaw(String value) {
        try {
            return mapper.readTree(value);
        } catch (com.fasterxml.jackson.core.JsonProcessingException ex) {
            throw new IllegalArgumentException("invalid raw document");
        }
    }

    static Activity toActivity(
            Contract c,
            String record,
            String hash,
            JsonNode raw,
            Instant collected,
            List<PersonRef> people) {
        validateContract(c);
        String sourceId = required(raw, c.fields().get("id"), "source identifier");
        String title = required(raw, c.fields().get("title"), "title");
        String url = TrackingPolicy.officialUrl(required(raw, c.fields().get("url"), "source URL"));
        String publishedValue = required(raw, c.fields().get("publishedAt"), "publication date");
        Instant published = sourceTime(publishedValue);
        String occurredValue = value(raw, c.fields().get("occurredAt"));
        Instant occurred = occurredValue == null ? null : sourceTime(occurredValue);
        String rawStage = value(raw, c.fields().get("stage"));
        String stage =
                c.stageMap() == null
                        ? "unknown"
                        : c.stageMap().getOrDefault(rawStage == null ? "" : rawStage, "unknown");
        String billValue =
                "bill".equals(c.kind()) ? sourceId : value(raw, c.fields().get("billId"));
        String billId = billValue == null ? null : "b_" + TrackingRepository.hash(billValue);
        List<Activity.Vote> votes = List.of();
        if ("vote".equals(c.kind())) {
            TrackingPolicy.require(people.size() == 1, "vote requires one verified person");
            String session = required(raw, c.fields().get("sessionId"), "vote session");
            String result = required(raw, c.fields().get("voteResult"), "vote result");
            String normalized =
                    c.voteMap() == null ? "unknown" : c.voteMap().getOrDefault(result, "unknown");
            votes =
                    List.of(
                            new Activity.Vote(
                                    people.get(0).id(),
                                    people.get(0).name(),
                                    normalized,
                                    "s_" + TrackingRepository.hash(session)));
        }
        String coverage = "공개 원문에 명시된 필드만 정제했습니다. 원천의 전체 제공 범위는 별도 검증이 필요합니다.";
        if (publishedValue.length() == 10 || occurredValue != null && occurredValue.length() == 10)
            coverage += " 날짜만 공개된 값의 시각은 확인되지 않았습니다(한국 표준시 날짜 기준).";
        Activity activity =
                new Activity(
                        "a_" + TrackingRepository.hash(c.sourceKey() + "|" + record),
                        c.kind(),
                        title,
                        null,
                        stage,
                        people.stream().map(PersonRef::id).toList(),
                        c.topics() == null ? List.of() : c.topics(),
                        billId,
                        occurred,
                        published,
                        collected,
                        url,
                        List.of(
                                new Activity.Evidence(
                                        "ev_"
                                                + TrackingRepository.hash(
                                                        c.sourceKey() + "|" + record),
                                        url,
                                        null,
                                        "source="
                                                + c.sourceKey()
                                                + "; record="
                                                + record
                                                + "; id="
                                                + sourceId,
                                        hash)),
                        votes,
                        coverage,
                        false,
                        "pending");
        new TrackingPolicy().validate(activity);
        return TrackingProjectionVersion.derive(
                activity, TrackingProjectionVersion.ROW_REVISION, c, List.of());
    }

    static void validateContract(Contract c) {
        TrackingPolicy.require(
                c != null && c.verifiedContract(), "operator-verified source contract required");
        TrackingPolicy.id(c.sourceKey());
        TrackingPolicy.require(
                List.of("bill", "vote", "announcement").contains(c.kind()),
                "unsupported projection type");
        TrackingPolicy.require(
                c.limit() >= 1 && c.limit() <= 500, "projection limit must be 1..500");
        TrackingPolicy.require(
                c.fields() != null && c.fields().size() <= 20, "field contract required");
        c.fields()
                .values()
                .forEach(
                        field ->
                                TrackingPolicy.require(
                                        field != null && field.matches("[A-Z0-9_]{1,100}"),
                                        "invalid field contract"));
    }

    private static String value(JsonNode raw, String field) {
        if (field == null) return null;
        JsonNode value = raw.get(field);
        return value == null || value.isNull() || value.asText().isBlank() ? null : value.asText();
    }

    private static String required(JsonNode raw, String field, String label) {
        String value = value(raw, field);
        if (value == null) throw new IllegalArgumentException("missing " + label);
        return value;
    }

    private static Instant sourceTime(String value) {
        try {
            return Instant.parse(value);
        } catch (DateTimeParseException ex) {
            try {
                return LocalDate.parse(value).atStartOfDay(ZoneId.of("Asia/Seoul")).toInstant();
            } catch (DateTimeParseException invalid) {
                throw new IllegalArgumentException("unsupported source date format");
            }
        }
    }
}
