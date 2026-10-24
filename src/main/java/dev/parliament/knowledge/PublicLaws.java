package dev.parliament.knowledge;

import java.time.Instant;
import java.time.LocalDate;
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;
import java.time.format.ResolverStyle;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.r2dbc.core.DatabaseClient;
import reactor.core.publisher.Mono;
import static dev.parliament.knowledge.KnowledgeBatch.*;

/** Only reviewed legal metadata is exposed, without raw storage keys or API credentials. */
public final class PublicLaws {
    public record Evidence(String label, String text, String locator) {}
    public record Law(String id, String lawId, String mst, String title, String agency,
            String promulgationNumber, LocalDate promulgatedDate, LocalDate effectiveDate,
            Instant collectedAt, String sourceUrl, String sourceVersion, String extractionVersion,
            List<Evidence> evidence) {}
    public record Page(List<Law> items, String coverage, String nextCursor) {}

    private static final String PREFIX = "json:법령.기본정보.";
    private static final Map<String, String> FIELDS = Map.of(
            "법령명_한글", "법령명", "법령ID", "법령 ID", "공포일자", "공포일",
            "시행일자", "시행일", "공포번호", "공포번호", "소관부처.content", "소관부처");
    private final DatabaseClient db;
    private final KnowledgeJson json;

    public PublicLaws(DatabaseClient db, ObjectMapper mapper) {
        this.db = db;
        this.json = new KnowledgeJson(mapper);
    }

    public Mono<Page> list() {
        // Choose the latest published version of each fixed document before checking rights.
        return db.sql("""
                SELECT document FROM (
                    SELECT j.document, j.document_id,
                        ROW_NUMBER() OVER(PARTITION BY j.document_id
                            ORDER BY b.reviewed_at DESC, b.batch_id DESC) AS document_rank
                    FROM knowledge_batch b,
                    JSON_TABLE(b.payload, '$.documents[*]' COLUMNS(
                        document JSON PATH '$',
                        document_id VARCHAR(128) PATH '$.id',
                        source_key VARCHAR(100) PATH '$.sourceKey'
                    )) j
                    WHERE b.review_state='published' AND j.source_key='law'
                ) reviewed WHERE document_rank=1 ORDER BY document_id LIMIT 50
                """).map((row, metadata) -> json.read(row.get("document", String.class), Document.class))
                .all().map(PublicLaws::project).filter(Optional::isPresent).map(Optional::get)
                .collectList().map(items -> new Page(items,
                        "공개 검수된 법령 기본정보 중 최대 50건입니다. 전체 법령을 수집한 목록이 아니며, 시행 상태·정책 효과를 판단하지 않습니다.", null));
    }

    static Optional<Law> project(Document document) {
        if (!"law".equals(document.sourceKey()) || !"allowed".equals(document.licenseStatus())
                || !List.of("available", "partial").contains(document.bodyStatus())
                || !document.recordKey().matches("[0-9]{1,12}:[0-9]{1,12}")) return Optional.empty();
        try {
            String[] identity = document.recordKey().split(":");
            String lawId = identity[0], mst = identity[1];
            if (!document.id().equals("law_" + lawId + "_" + mst)) return Optional.empty();
            String apiSource = "https://www.law.go.kr/DRF/lawService.do?target=law&MST=" + mst + "&type=JSON";
            String source = "https://www.law.go.kr/LSW/lsInfoP.do?lsiSeq=" + mst;
            if (!apiSource.equals(document.sourceUrl()) && !source.equals(document.sourceUrl())) return Optional.empty();
            Map<String, Segment> fields = new LinkedHashMap<>();
            for (Segment segment : document.segments()) {
                if (!segment.locator().startsWith(PREFIX)) continue;
                String field = segment.locator().substring(PREFIX.length());
                if (FIELDS.containsKey(field) && fields.putIfAbsent(field, segment) != null) return Optional.empty();
            }
            if (!document.title().equals(value(fields, "법령명_한글"))
                    || !lawId.equals(value(fields, "법령ID"))) return Optional.empty();
            LocalDate promulgated = date(value(fields, "공포일자"));
            LocalDate effective = date(value(fields, "시행일자"));
            if (promulgated != null && (document.publishedAt() == null
                    || !promulgated.equals(document.publishedAt().atZone(ZoneId.of("Asia/Seoul")).toLocalDate()))) return Optional.empty();
            var evidence = fields.entrySet().stream()
                    .map(entry -> new Evidence(FIELDS.get(entry.getKey()), entry.getValue().text(), entry.getValue().locator())).toList();
            return Optional.of(new Law(document.id(), lawId, mst, document.title(), value(fields, "소관부처.content"),
                    value(fields, "공포번호"), promulgated, effective, document.collectedAt(), source,
                    document.version(), document.extractionVersion(), evidence));
        } catch (IllegalArgumentException | java.time.DateTimeException exception) {
            return Optional.empty();
        }
    }

    private static String value(Map<String, Segment> fields, String key) {
        Segment field = fields.get(key);
        return field == null ? null : field.text();
    }

    private static LocalDate date(String raw) {
        if (raw == null || raw.equals("00000000")) return null;
        if (!raw.matches("[0-9]{8}")) throw new IllegalArgumentException("invalid law date");
        return LocalDate.parse(raw, DateTimeFormatter.ofPattern("uuuuMMdd").withResolverStyle(ResolverStyle.STRICT));
    }
}
