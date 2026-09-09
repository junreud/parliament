package dev.parliament.config;

import com.fasterxml.jackson.databind.ObjectMapper;
import dev.parliament.api.OpenAssemblyResponseParser;
import dev.parliament.api.ParliamentApiClient;
import dev.parliament.api.WebClientParliamentApiClient;
import dev.parliament.api.OpenAssemblyWebClientFactory;
import dev.parliament.domain.ParliamentRecordNormalizer;
import dev.parliament.persistence.ParliamentStagingRepository;
import dev.parliament.persistence.R2dbcParliamentStagingRepository;
import dev.parliament.service.ParliamentIngestionService;
import dev.parliament.service.ParliamentParameterResolver;
import dev.parliament.service.ParliamentSocialUrlPolicy;
import dev.parliament.service.ParliamentSocialVerificationService;
import dev.parliament.service.SocialLinkClient;
import dev.parliament.service.WebClientSocialLinkClient;
import dev.parliament.service.ParliamentJobGuard;
import dev.parliament.service.ParliamentDashboardService;
import io.r2dbc.spi.ConnectionFactory;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.r2dbc.core.DatabaseClient;
import org.springframework.r2dbc.connection.R2dbcTransactionManager;
import org.springframework.transaction.reactive.TransactionalOperator;
import org.springframework.scheduling.annotation.EnableScheduling;
import org.springframework.web.reactive.function.client.WebClient;

import java.time.Clock;

@Configuration
@EnableScheduling
@EnableConfigurationProperties(ParliamentIngestionProperties.class)
@ConditionalOnProperty(prefix = "parliament.ingestion", name = "enabled", havingValue = "true")
public class ParliamentIngestionConfiguration {
    @Bean
    ParliamentSourceCatalog parliamentSourceCatalog(ObjectMapper objectMapper) {
        return ParliamentSourceCatalog.loadDefault(objectMapper);
    }

    @Bean
    ParliamentParameterPlanCatalog parliamentParameterPlanCatalog(ObjectMapper objectMapper) {
        return ParliamentParameterPlanCatalog.loadDefault(objectMapper);
    }

    @Bean
    Clock parliamentClock() {
        return Clock.systemUTC();
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
        WebClient webClient = new OpenAssemblyWebClientFactory().create(webClientBuilder, properties);
        return new WebClientParliamentApiClient(webClient, properties, parser);
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
            ParliamentIngestionProperties properties,
            ParliamentParameterResolver parameterResolver,
            Clock parliamentClock
    ) {
        return new ParliamentIngestionService(
                apiClient, repository, normalizer, catalog, properties, parameterResolver,
                parliamentClock);
    }

    @Bean
    ParliamentParameterResolver parliamentParameterResolver(
            ParliamentParameterPlanCatalog plans,
            ParliamentStagingRepository repository,
            ParliamentIngestionProperties properties,
            Clock parliamentClock
    ) {
        return new ParliamentParameterResolver(plans, repository, properties, parliamentClock);
    }

    @Bean
    ParliamentSocialUrlPolicy parliamentSocialUrlPolicy() {
        return new ParliamentSocialUrlPolicy();
    }

    @Bean
    SocialLinkClient parliamentSocialLinkClient(
            WebClient.Builder webClientBuilder,
            ParliamentIngestionProperties properties
    ) {
        WebClient webClient = new OpenAssemblyWebClientFactory().create(webClientBuilder, properties);
        return new WebClientSocialLinkClient(webClient);
    }

    @Bean
    ParliamentSocialVerificationService parliamentSocialVerificationService(
            SocialLinkClient parliamentSocialLinkClient,
            ParliamentStagingRepository repository,
            ParliamentSocialUrlPolicy parliamentSocialUrlPolicy,
            Clock parliamentClock
    ) {
        return new ParliamentSocialVerificationService(
                parliamentSocialLinkClient, repository, parliamentSocialUrlPolicy, parliamentClock);
    }

    @Bean
    ParliamentJobGuard parliamentJobGuard() {
        return new ParliamentJobGuard();
    }

    @Bean
    ParliamentDashboardService parliamentDashboardService(
            ParliamentStagingRepository repository,
            ParliamentSourceCatalog sources,
            ParliamentParameterPlanCatalog plans,
            ParliamentIngestionProperties properties,
            Clock parliamentClock
    ) {
        return new ParliamentDashboardService(
                repository, sources, plans, properties, parliamentClock);
    }
}
