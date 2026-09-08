package dev.parliament.config;

import com.fasterxml.jackson.databind.ObjectMapper;
import dev.parliament.api.OpenAssemblyResponseParser;
import dev.parliament.api.ParliamentApiClient;
import dev.parliament.api.WebClientParliamentApiClient;
import dev.parliament.domain.ParliamentRecordNormalizer;
import dev.parliament.persistence.ParliamentStagingRepository;
import dev.parliament.persistence.R2dbcParliamentStagingRepository;
import dev.parliament.service.ParliamentIngestionService;
import io.r2dbc.spi.ConnectionFactory;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.r2dbc.core.DatabaseClient;
import org.springframework.r2dbc.connection.R2dbcTransactionManager;
import org.springframework.transaction.reactive.TransactionalOperator;
import org.springframework.web.reactive.function.client.WebClient;

@Configuration
@EnableConfigurationProperties(ParliamentIngestionProperties.class)
@ConditionalOnProperty(prefix = "parliament.ingestion", name = "enabled", havingValue = "true")
public class ParliamentIngestionConfiguration {
    @Bean
    ParliamentSourceCatalog parliamentSourceCatalog(ObjectMapper objectMapper) {
        return ParliamentSourceCatalog.loadDefault(objectMapper);
    }

    @Bean
    OpenAssemblyResponseParser openAssemblyResponseParser() {
        return new OpenAssemblyResponseParser();
    }

    @Bean
    ParliamentRecordNormalizer parliamentRecordNormalizer(ObjectMapper objectMapper) {
        return new ParliamentRecordNormalizer(objectMapper);
    }

    @Bean
    ParliamentApiClient parliamentApiClient(
            WebClient.Builder webClientBuilder,
            ParliamentIngestionProperties properties,
            OpenAssemblyResponseParser parser
    ) {
        return new WebClientParliamentApiClient(webClientBuilder.build(), properties, parser);
    }

    @Bean
    TransactionalOperator parliamentTransactionalOperator(ConnectionFactory connectionFactory) {
        return TransactionalOperator.create(new R2dbcTransactionManager(connectionFactory));
    }

    @Bean
    ParliamentStagingRepository parliamentStagingRepository(
            DatabaseClient databaseClient,
            TransactionalOperator parliamentTransactionalOperator
    ) {
        return new R2dbcParliamentStagingRepository(databaseClient, parliamentTransactionalOperator);
    }

    @Bean
    ParliamentIngestionService parliamentIngestionService(
            ParliamentApiClient apiClient,
            ParliamentStagingRepository repository,
            ParliamentRecordNormalizer normalizer,
            ParliamentSourceCatalog catalog,
            ParliamentIngestionProperties properties
    ) {
        return new ParliamentIngestionService(apiClient, repository, normalizer, catalog, properties);
    }
}
