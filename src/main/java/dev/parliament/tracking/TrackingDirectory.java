package dev.parliament.tracking;

import org.springframework.r2dbc.core.DatabaseClient;

import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;

import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

public final class TrackingDirectory {
    public record Person(
            String id,
            String name,
            String kind,
            String organization,
            String role,
            List<Activity> activities) {}

    public record Bill(
            String id,
            String title,
            String stage,
            List<Activity> activities,
            List<Activity.Vote> votes,
            String sourceUrl) {}

    public record Coverage(
            String source, String status, Instant lastObservedAt, String range, String note) {}

    private final DatabaseClient db;
    private final TrackingRepository events;
    private final dev.parliament.knowledge.KnowledgeIdentity identities;
    private final dev.parliament.knowledge.KnowledgeDirectory knowledge;

    public TrackingDirectory(DatabaseClient db, TrackingRepository events) {
        this(db,events,new dev.parliament.knowledge.KnowledgeIdentity(db,false));
    }
    public TrackingDirectory(DatabaseClient db, TrackingRepository events,dev.parliament.knowledge.KnowledgeIdentity identities) {
        this.db = db;
        this.events = events;
        this.identities=identities;
        this.knowledge=new dev.parliament.knowledge.KnowledgeDirectory(db,events,identities);
    }

    public Flux<Person> people(String query) {
        if (query != null) TrackingPolicy.text(query, 100, "query");
        if(identities.hasStorage())return identities.refresh().thenMany(knowledge.people(query));
        var spec =
                db.sql(
                                """
                SELECT CONCAT('p_',SHA2(p.identity_key,256)) AS public_id,p.canonical_name,p.person_kind,
                  (SELECT x.organization FROM parliament_person_position x WHERE x.identity_key=p.identity_key ORDER BY observed_at DESC,position_key DESC LIMIT 1) AS organization,
                  (SELECT x.position_title FROM parliament_person_position x WHERE x.identity_key=p.identity_key ORDER BY observed_at DESC,position_key DESC LIMIT 1) AS position_title
                FROM parliament_person p WHERE (:query='' OR p.canonical_name LIKE :pattern)
                ORDER BY p.canonical_name,p.identity_key LIMIT 100
                """)
                        .bind("query", query == null ? "" : query)
                        .bind("pattern", query == null ? "%" : "%" + escapeLike(query) + "%");
        return spec.map(
                        (row, meta) ->
                                new Person(
                                        row.get("public_id", String.class),
                                        row.get("canonical_name", String.class),
                                        row.get("person_kind", String.class),
                                        row.get("organization", String.class),
                                        row.get("position_title", String.class),
                                        List.of()))
                .all();
    }

    public Mono<Person> person(String id) {
        TrackingPolicy.id(id);
        if(identities.hasStorage())return identities.refresh().then(knowledge.person(id));
        return db.sql(
                        """
                SELECT p.canonical_name,p.person_kind,
                  (SELECT x.organization FROM parliament_person_position x WHERE x.identity_key=p.identity_key ORDER BY observed_at DESC,position_key DESC LIMIT 1) AS organization,
                  (SELECT x.position_title FROM parliament_person_position x WHERE x.identity_key=p.identity_key ORDER BY observed_at DESC,position_key DESC LIMIT 1) AS position_title
                FROM parliament_person p WHERE CONCAT('p_',SHA2(p.identity_key,256))=:id
                """)
                .bind("id", id)
                .map(
                        (row, meta) ->
                                new Person(
                                        id,
                                        row.get("canonical_name", String.class),
                                        row.get("person_kind", String.class),
                                        row.get("organization", String.class),
                                        row.get("position_title", String.class),
                                        List.of()))
                .one()
                .switchIfEmpty(Mono.error(TrackingRepository.notFound()))
                .flatMap(
                        person ->
                                events.feed(id, null, null, null, null, null, 100)
                                        .map(
                                                page ->
                                                        new Person(
                                                                id,
                                                                person.name(),
                                                                person.kind(),
                                                                person.organization(),
                                                                person.role(),
                                                                page.items())));
    }

    public Flux<Bill> bills(String query) {
        if (query != null) TrackingPolicy.text(query, 200, "query");
        var spec =
                db.sql(
                                """
                SELECT v.activity,v.corrected FROM tracking_event e JOIN tracking_event_version v
                  ON v.event_id=e.event_id AND v.version_id=e.latest_version
                WHERE v.review_state='published' AND v.bill_id IS NOT NULL AND v.activity_type='bill'
                  AND (:query='' OR MATCH(v.title,v.summary) AGAINST(:query IN NATURAL LANGUAGE MODE))
                """ + events.knowledgePublication() + " ORDER BY v.published_at DESC,v.event_id DESC LIMIT 100")
                        .bind("query", query == null ? "" : query);
        Flux<Bill> result = spec.map((row, meta) -> events.parse(row.get("activity", String.class)))
                .all()
                .distinct(Activity::billId)
                .map(
                        a ->
                                new Bill(
                                        a.billId(),
                                        a.title(),
                                        a.stage(),
                                        List.of(),
                                        List.of(),
                                        a.sourceUrl()));
        return identities.hasStorage()?identities.refresh().thenMany(result.concatWith(knowledge.bills(query)).distinct(Bill::id).take(100)):result;
    }

    public Mono<Bill> bill(String id) {
        TrackingPolicy.id(id);
        return events.feed(null, null, id, null, null, null, 100)
                .flatMap(
                        page -> {
                            if (page.items().isEmpty())
                                return identities.hasStorage()?knowledge.bill(id):Mono.error(TrackingRepository.notFound());
                            Activity latest = page.items().get(0);
                            Activity description =
                                    page.items().stream()
                                            .filter(a -> a.type().equals("bill"))
                                            .findFirst()
                                            .orElse(latest);
                            LinkedHashMap<String, Activity.Vote> votes = new LinkedHashMap<>();
                            page.items()
                                    .forEach(
                                            a ->
                                                    a.votes()
                                                            .forEach(
                                                                    v ->
                                                                            votes.putIfAbsent(
                                                                                    v.sessionId()
                                                                                            + ":"
                                                                                            + v
                                                                                                    .personId(),
                                                                                    v)));
                            return Mono.just(
                                    new Bill(
                                            id,
                                            description.title(),
                                            description.stage(),
                                            page.items(),
                                            List.copyOf(votes.values()),
                                            description.sourceUrl()));
                        });
    }

    public Flux<Coverage> coverage() {
        return db.sql(
                        """
                SELECT source_key,status,last_finished_at,last_error_code FROM parliament_source_sync_state ORDER BY source_key
                """)
                .map(
                        (row, meta) ->
                                new Coverage(
                                        row.get("source_key", String.class),
                                        "COMPLETE".equals(row.get("status", String.class))
                                                ? "collected-contract-pending"
                                                : row.get("status", String.class).toLowerCase(),
                                        row.get("last_finished_at", Instant.class),
                                        "수집된 공개 기록",
                                        row.get("last_error_code", String.class) == null
                                                ? "수집 상태와 공개용 계약 검증은 별개입니다. 제공 범위는 출처별 확인이 필요합니다."
                                                : "수집 실패: "
                                                        + row.get("last_error_code", String.class)))
                .all()
                .collectMap(Coverage::source)
                .flatMapMany(
                        observed -> {
                            java.util.TreeMap<String, Coverage> sources =
                                    new java.util.TreeMap<>(knownCoverage());
                            sources.putAll(observed);
                            return Flux.fromIterable(sources.values());
                        });
    }

    private Map<String, Coverage> knownCoverage() {
        java.util.TreeMap<String, Coverage> result = new java.util.TreeMap<>();
        try (var stream =
                new org.springframework.core.io.ClassPathResource(
                                "parliament/open-assembly-sources.json")
                        .getInputStream()) {
            var definitions =
                    new com.fasterxml.jackson.databind.ObjectMapper()
                            .readTree(stream)
                            .get("definitions");
            definitions.forEach(
                    source -> {
                        String key = source.get("key").asText();
                        result.put(
                                key,
                                new Coverage(
                                        key,
                                        "not-collected",
                                        null,
                                        "미검증",
                                        source.get("name").asText()
                                                + ": 수집 이력과 원천 제공 범위를 아직 확인하지 않았습니다."));
                    });
        } catch (java.io.IOException ex) {
            throw new IllegalStateException("source catalog unavailable", ex);
        }
        for (String source :
                List.of("president-official", "prime-minister-official", "ministry-briefings"))
            result.put(
                    source,
                    new Coverage(
                            source,
                            "contract-pending",
                            null,
                            "최근 90일 목표",
                            "공식 문서 계약과 이용 조건을 검증한 뒤 공개합니다. 현재 수집 완료를 보장하지 않습니다."));
        return result;
    }

    private static String escapeLike(String query) {
        return query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_");
    }
}
