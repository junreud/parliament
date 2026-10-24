package dev.parliament.beta;

import java.time.Clock;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.r2dbc.core.DatabaseClient;
import org.springframework.scheduling.annotation.EnableScheduling;

/** Retention is intentionally independent of beta.enabled, which controls new public admissions. */
@Configuration
@EnableScheduling
public class BetaRetentionConfiguration {
    @Bean
    BetaRetention betaRetention(DatabaseClient database) { return new BetaRetention(database); }

    @Bean
    BetaHousekeeping betaHousekeeping(BetaRetention retention) {
        return new BetaHousekeeping(retention, Clock.systemUTC());
    }
}
