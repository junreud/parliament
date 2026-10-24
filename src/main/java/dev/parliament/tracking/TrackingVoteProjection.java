package dev.parliament.tracking;

import com.fasterxml.jackson.databind.ObjectMapper;

import org.springframework.r2dbc.core.DatabaseClient;

import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;

import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Objects;

/** One public event per verified bill/session; incomplete groups remain unavailable. */
final class TrackingVoteProjection {
    private record Group(String bill, String session) {}

    private record Raw(String record, String hash, String payload, Instant collected) {}

    private final DatabaseClient db;
    private final TrackingRepository repository;
    private final ObjectMapper mapper;
    private final dev.parliament.knowledge.KnowledgeIdentity identities;

    TrackingVoteProjection(DatabaseClient db, TrackingRepository repository, ObjectMapper mapper) {
        this(db,repository,mapper,new dev.parliament.knowledge.KnowledgeIdentity(db,false));
    }
    TrackingVoteProjection(DatabaseClient db, TrackingRepository repository, ObjectMapper mapper,dev.parliament.knowledge.KnowledgeIdentity identities) {
        this.db = db;
        this.repository = repository;
        this.mapper = mapper;
        this.identities = identities;
    }

    Mono<TrackingProjection.Result> project(TrackingProjection.Contract contract) {
        String billField = contract.fields().get("billId"),
                sessionField = contract.fields().get("sessionId");
        TrackingPolicy.require(
                billField != null
                        && sessionField != null
                        && contract.fields().get("personId") != null
                        && contract.personNamespace() != null,
                "verified bill,session and person namespace required");
        var cursor =
                contract.cursor() == null
                        ? null
                        : TrackingProjectionCursor.decode(
                                contract.cursor(), contract.sourceKey(), contract.kind());
        String billPath = "$." + billField, sessionPath = "$." + sessionField;
        java.util.Set<String> reasons = new java.util.TreeSet<>();
        java.util.concurrent.atomic.AtomicInteger
                imported = new java.util.concurrent.atomic.AtomicInteger(),
                skipped = new java.util.concurrent.atomic.AtomicInteger();
        int limit = Math.min(contract.limit(), 20);
        return db.sql(
                        """
                SELECT JSON_UNQUOTE(JSON_EXTRACT(raw_payload,:billPath)) AS bill_key,
                       JSON_UNQUOTE(JSON_EXTRACT(raw_payload,:sessionPath)) AS session_key
                FROM parliament_source_record WHERE source_key=:source
                  AND JSON_UNQUOTE(JSON_EXTRACT(raw_payload,:billPath))<>'' AND JSON_UNQUOTE(JSON_EXTRACT(raw_payload,:sessionPath))<>''
                  AND (JSON_UNQUOTE(JSON_EXTRACT(raw_payload,:billPath))>:afterBill
                    OR (JSON_UNQUOTE(JSON_EXTRACT(raw_payload,:billPath))=:afterBill AND JSON_UNQUOTE(JSON_EXTRACT(raw_payload,:sessionPath))>:afterSession))
                GROUP BY bill_key,session_key ORDER BY bill_key,session_key LIMIT :limit
                """)
                .bind("source", contract.sourceKey())
                .bind("billPath", billPath)
                .bind("sessionPath", sessionPath)
                .bind("afterBill", cursor == null ? "" : cursor.bill())
                .bind("afterSession", cursor == null ? "" : cursor.session())
                .bind("limit", limit + 1)
                .map(
                        (row, meta) ->
                                new Group(
                                        row.get("bill_key", String.class),
                                        row.get("session_key", String.class)))
                .all()
                .collectList()
                .flatMap(
                        groups -> {
                            boolean more = groups.size() > limit;
                            List<Group> page = more ? groups.subList(0, limit) : groups;
                            String next =
                                    more
                                            ? new TrackingProjectionCursor(
                                                            contract.sourceKey(),
                                                            contract.kind(),
                                                            null,
                                                            page.get(page.size() - 1).bill(),
                                                            page.get(page.size() - 1).session())
                                                    .encode()
                                            : null;
                            return Flux.fromIterable(page)
                                    .concatMap(
                                            group ->
                                                    projectGroup(
                                                                    contract,
                                                                    group,
                                                                    billPath,
                                                                    sessionPath)
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
                                                            new TrackingProjection.Result(
                                                                    imported.get(),
                                                                    skipped.get(),
                                                                    java.util.stream.Stream.concat(
                                                                                    java.util.stream
                                                                                            .Stream
                                                                                            .of(
                                                                                                    "검증된 법안·표결회차별"
                                                                                                        + " 전체 행을"
                                                                                                        + " 한 사건으로"
                                                                                                        + " 묶어 초안으로"
                                                                                                        + " 적재했습니다.",
                                                                                                    "법안·회차"
                                                                                                        + " 키가 없는"
                                                                                                        + " 행은 그룹에"
                                                                                                        + " 포함하지"
                                                                                                        + " 않습니다."
                                                                                                        + " 500행"
                                                                                                        + " 초과 또는"
                                                                                                        + " 필수 필드가"
                                                                                                        + " 빠진 회차는"
                                                                                                        + " 일부만 공개하지"
                                                                                                        + " 않고 건너뜁니다."),
                                                                                    reasons
                                                                                            .stream())
                                                                            .toList(),
                                                                    next)));
                        });
    }

    private Mono<TrackingRepository.ImportResult> projectGroup(
            TrackingProjection.Contract contract,
            Group group,
            String billPath,
            String sessionPath) {
        return db.sql(
                        """
                SELECT record_key,payload_hash,raw_payload,content_changed_at FROM parliament_source_record
                WHERE source_key=:source AND JSON_UNQUOTE(JSON_EXTRACT(raw_payload,:billPath))=:bill
                  AND JSON_UNQUOTE(JSON_EXTRACT(raw_payload,:sessionPath))=:session ORDER BY record_key LIMIT 501
                """)
                .bind("source", contract.sourceKey())
                .bind("billPath", billPath)
                .bind("sessionPath", sessionPath)
                .bind("bill", group.bill())
                .bind("session", group.session())
                .map(
                        (row, meta) ->
                                new Raw(
                                        row.get("record_key", String.class),
                                        row.get("payload_hash", String.class),
                                        row.get("raw_payload", String.class),
                                        row.get("content_changed_at", Instant.class)))
                .all()
                .collectList()
                .flatMap(
                        rows -> {
                            TrackingPolicy.require(
                                    !rows.isEmpty() && rows.size() <= 500,
                                    "vote session exceeds verified row bound");
                            return Flux.fromIterable(rows)
                                    .concatMap(row -> individual(contract, row))
                                    .collectList()
                                    .flatMap(
                                            activities ->
                                                    repository.importDraft(
                                                            combine(
                                                                    contract.sourceKey(),
                                                                    group.bill(),
                                                                    group.session(),
                                                                    activities)));
                        });
    }

    private Mono<Activity> individual(TrackingProjection.Contract contract, Raw row) {
        return Mono.defer(
                () -> {
                    com.fasterxml.jackson.databind.JsonNode raw;
                    try {
                        raw = mapper.readTree(row.payload());
                    } catch (com.fasterxml.jackson.core.JsonProcessingException ex) {
                        return Mono.error(new IllegalArgumentException("invalid source document"));
                    }
                    var externalNode = raw.get(contract.fields().get("personId"));
                    TrackingPolicy.require(
                            externalNode != null
                                    && !externalNode.isNull()
                                    && !externalNode.asText().isBlank(),
                            "verified vote person identifier required");
                    return db.sql(
                            "SELECT " + identities.personSql() + """
                     AS public_id,p.canonical_name
                    FROM parliament_person_identifier i JOIN parliament_person p ON p.identity_key=i.identity_key
                    WHERE i.identifier_namespace=:namespace AND i.external_id=:external
                    """)
                            .bind("namespace", contract.personNamespace())
                            .bind("external", externalNode.asText())
                            .map(
                                    (person, meta) ->
                                            new TrackingProjection.PersonRef(
                                                    person.get("public_id", String.class),
                                                    person.get("canonical_name", String.class)))
                            .all()
                            .collectList()
                            .map(
                                    people ->
                                            TrackingProjection.toActivity(
                                                    contract,
                                                    row.record(),
                                                    row.hash(),
                                                    raw,
                                                    row.collected(),
                                                    people));
                });
    }

    static Activity combine(String source, String bill, String session, List<Activity> rows) {
        TrackingPolicy.require(!rows.isEmpty(), "empty vote session");
        List<Activity> orderedRows =
                rows.stream()
                        .sorted(
                                java.util.Comparator.comparing(Activity::id)
                                        .thenComparing(Activity::version))
                        .toList();
        Activity first = orderedRows.get(0);
        LinkedHashMap<String, Activity.Vote> votes = new LinkedHashMap<>();
        LinkedHashMap<String, Activity.Evidence> evidence = new LinkedHashMap<>();
        for (Activity row : orderedRows) {
            TrackingPolicy.require(
                    Objects.equals(first.billId(), row.billId())
                            && Objects.equals(first.publishedAt(), row.publishedAt())
                            && Objects.equals(first.occurredAt(), row.occurredAt())
                            && first.stage().equals(row.stage()),
                    "conflicting vote session metadata");
            for (Activity.Vote vote : row.votes()) {
                String key = vote.sessionId() + ":" + vote.personId();
                Activity.Vote previous = votes.putIfAbsent(key, vote);
                TrackingPolicy.require(
                        previous == null || previous.equals(vote), "conflicting individual votes");
            }
            row.evidence().forEach(item -> evidence.put(item.id(), item));
        }
        Activity merged =
                new Activity(
                        "vote_" + TrackingRepository.hash(source + "|" + bill + "|" + session),
                        "vote",
                        first.title(),
                        null,
                        first.stage(),
                        votes.values().stream().map(Activity.Vote::personId).distinct().toList(),
                        rows.stream().flatMap(a -> a.topics().stream()).distinct().toList(),
                        first.billId(),
                        first.occurredAt(),
                        first.publishedAt(),
                        rows.stream()
                                .map(Activity::collectedAt)
                                .max(Instant::compareTo)
                                .orElseThrow(),
                        first.sourceUrl(),
                        List.copyOf(evidence.values()),
                        List.copyOf(votes.values()),
                        first.coverage()
                                + " 검증된 표결회차에 공개된 개별 기록 "
                                + votes.size()
                                + "건입니다. 미공개 의원의 입장을 추정하지 않습니다.",
                        false,
                        "pending");
        new TrackingPolicy().validate(merged);
        return TrackingProjectionVersion.derive(
                merged,
                TrackingProjectionVersion.VOTE_REVISION,
                null,
                rows.stream().map(Activity::version).toList());
    }
}
