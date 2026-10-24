package dev.parliament.beta;

import java.time.Duration;
import java.time.Instant;
import java.time.ZoneId;
import org.springframework.r2dbc.core.DatabaseClient;
import reactor.core.publisher.Mono;

/** Cleanup survives admission disablement and safely tolerates an installation without beta tables. */
public final class BetaRetention {
    public static final Duration SAFETY_MARGIN = Duration.ofHours(1);
    private final DatabaseClient database;

    public BetaRetention(DatabaseClient database) { this.database = database; }

    public Mono<Void> purge(Instant now) {
        Instant cutoff = now.plus(SAFETY_MARGIN);
        return database.sql("""
                SELECT table_name FROM information_schema.tables
                WHERE table_schema=DATABASE() AND table_name IN ('beta_participant','beta_acquisition')
                """).map((row, metadata) -> row.get("table_name", String.class)).all().collectList()
                .flatMap(tables -> {
                    Mono<Void> participants = tables.contains("beta_participant")
                            ? database.sql("DELETE FROM beta_participant WHERE expires_at<=:cutoff")
                                    .bind("cutoff", cutoff).fetch().rowsUpdated().then()
                            : Mono.empty();
                    // Aggregate rows have day precision; erase the intersecting oldest day early.
                    Mono<Void> acquisition = tables.contains("beta_acquisition")
                            ? database.sql("DELETE FROM beta_acquisition WHERE day<=:cutoffDay")
                                    .bind("cutoffDay", cutoff.minus(BetaPolicy.RETENTION)
                                            .atZone(ZoneId.of("Asia/Seoul")).toLocalDate())
                                    .fetch().rowsUpdated().then()
                            : Mono.empty();
                    return participants.then(acquisition);
                });
    }
}
