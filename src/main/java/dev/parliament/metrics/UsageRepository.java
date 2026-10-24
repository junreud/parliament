package dev.parliament.metrics;

import org.springframework.r2dbc.core.DatabaseClient;
import reactor.core.publisher.Mono;
import java.time.Instant;

/** First-party aggregate product measurement without recording political targets. */
public final class UsageRepository {
    public record Report(long activated, long week4Eligible, long week4Returned,
                         Double week4Retention, long relevanceResponses, long relevancePositive) {}
    private final DatabaseClient database;
    public UsageRepository(DatabaseClient database) { this.database = database; }

    public Mono<Void> record(String userId, String event, Boolean rating, Instant at) {
        if (userId == null || userId.isBlank() || event == null || !java.util.Set.of("follow_saved", "activity_opened", "relevance").contains(event)
                || (event.equals("relevance") != (rating != null))) {
            return Mono.error(new IllegalArgumentException("invalid usage event"));
        }
        var query = database.sql("""
                INSERT INTO tracking_usage_event(user_id, event_kind, rating, occurred_at)
                SELECT :userId, :event, :rating, :at
                WHERE (SELECT COUNT(*) FROM tracking_usage_event
                       WHERE user_id = :userId AND occurred_at >= DATE_SUB(:at, INTERVAL 1 HOUR)) < 120
                """).bind("userId", userId).bind("event", event).bind("at", at);
        query = rating == null ? query.bindNull("rating", Boolean.class) : query.bind("rating", rating);
        return query.fetch().rowsUpdated().then();
    }

    public Mono<Report> report(Instant from, Instant to, Instant now) {
        if (from == null || to == null || now == null || !from.isBefore(to)
                || java.time.Duration.between(from, to).toDays() > 366) {
            return Mono.error(new IllegalArgumentException("invalid metrics date range"));
        }
        Mono<long[]> cohorts = database.sql("""
                WITH followed AS (
                    SELECT user_id, MIN(occurred_at) AS followed_at FROM tracking_usage_event
                    WHERE event_kind='follow_saved' GROUP BY user_id
                ), activated AS (
                    SELECT e.user_id, MIN(e.occurred_at) AS activated_at
                    FROM tracking_usage_event e JOIN followed f ON f.user_id=e.user_id
                    WHERE e.event_kind='activity_opened' AND e.occurred_at >= f.followed_at
                    GROUP BY e.user_id
                )
                SELECT COUNT(*) AS activated,
                  COALESCE(SUM(a.activated_at <= DATE_SUB(:now, INTERVAL 28 DAY)),0) AS eligible,
                  COALESCE(SUM(a.activated_at <= DATE_SUB(:now, INTERVAL 28 DAY) AND EXISTS (
                    SELECT 1 FROM tracking_usage_event r WHERE r.user_id=a.user_id
                      AND r.event_kind='activity_opened'
                      AND r.occurred_at >= DATE_ADD(a.activated_at, INTERVAL 21 DAY)
                      AND r.occurred_at < DATE_ADD(a.activated_at, INTERVAL 28 DAY)
                  )),0) AS returned
                FROM activated a WHERE a.activated_at >= :from AND a.activated_at < :to
                """).bind("from", from).bind("to", to).bind("now", now)
                .map((row, meta) -> new long[]{number(row.get("activated")), number(row.get("eligible")), number(row.get("returned"))}).one();
        Mono<long[]> relevance = database.sql("""
                SELECT COUNT(*) AS responses, COALESCE(SUM(rating),0) AS positive
                FROM tracking_usage_event WHERE event_kind='relevance'
                  AND occurred_at >= :from AND occurred_at < :to
                """).bind("from", from).bind("to", to)
                .map((row, meta) -> new long[]{number(row.get("responses")), number(row.get("positive"))}).one();
        return cohorts.zipWith(relevance).map(values -> {
            long[] c = values.getT1(), r = values.getT2();
            return new Report(c[0], c[1], c[2], c[1] == 0 ? null : (double)c[2]/c[1], r[0], r[1]);
        });
    }
    private static long number(Object value) { return value == null ? 0 : ((Number)value).longValue(); }
}
