package dev.parliament.persistence;

import org.springframework.r2dbc.core.DatabaseClient;
import reactor.core.publisher.Flux;
import java.time.Instant;

/** Revisit active/unknown-status parents even when their root payload did not change. */
public final class ParliamentChildRefreshRepository {
    private final DatabaseClient database;
    public ParliamentChildRefreshRepository(DatabaseClient database) { this.database = database; }

    public Flux<String> values(String source, String field, Instant since, int limit) {
        if (source == null || source.isBlank() || field == null || !field.matches("[A-Z0-9_]+")
                || since == null || limit < 1 || limit > 100_000) {
            return Flux.error(new IllegalArgumentException("invalid child refresh query"));
        }
        return database.sql("""
                SELECT JSON_UNQUOTE(JSON_EXTRACT(raw_payload, :path)) AS parameter_value
                FROM parliament_source_record
                WHERE source_key = :source
                  AND JSON_EXTRACT(raw_payload, :path) IS NOT NULL
                  AND JSON_UNQUOTE(JSON_EXTRACT(raw_payload, :path)) <> ''
                  AND (
                    content_changed_at >= :since
                    OR COALESCE(JSON_UNQUOTE(JSON_EXTRACT(raw_payload, '$.PROC_RESULT_CD')), '')
                      NOT IN ('원안가결', '수정가결', '부결', '폐기', '철회', '대안반영폐기')
                  )
                GROUP BY parameter_value
                ORDER BY MAX(content_changed_at) DESC
                LIMIT :resultLimit
                """)
                .bind("path", "$." + field).bind("source", source)
                .bind("since", since).bind("resultLimit", limit)
                .map((row, metadata) -> row.get("parameter_value", String.class)).all();
    }
}
