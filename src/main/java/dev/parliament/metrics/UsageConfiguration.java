package dev.parliament.metrics;

import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.r2dbc.core.DatabaseClient;

@Configuration
@ConditionalOnProperty(prefix="tracking",name="enabled",havingValue="true")
public class UsageConfiguration {
    @Bean UsageRepository usageRepository(DatabaseClient database) { return new UsageRepository(database); }
}
