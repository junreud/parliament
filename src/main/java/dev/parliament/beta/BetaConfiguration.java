package dev.parliament.beta;

import io.r2dbc.spi.ConnectionFactory;
import java.time.Clock;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.r2dbc.connection.R2dbcTransactionManager;
import org.springframework.r2dbc.core.DatabaseClient;
import org.springframework.transaction.reactive.TransactionalOperator;

@Configuration
@ConditionalOnProperty(prefix = "beta", name = "enabled", havingValue = "true")
public class BetaConfiguration {
    @Bean
    BetaPolicy betaPolicy(@Value("${beta.public-base-url:http://localhost:3000}") String url) {
        return new BetaPolicy(url);
    }
    @Bean
    BetaRateLimiter betaRateLimiter() { return new BetaRateLimiter(); }
    @Bean
    Clock betaClock() { return Clock.systemUTC(); }
    @Bean
    BetaRepository betaRepository(DatabaseClient db, ConnectionFactory factory, BetaPolicy policy) {
        return new BetaRepository(db, TransactionalOperator.create(new R2dbcTransactionManager(factory)), policy);
    }
}
