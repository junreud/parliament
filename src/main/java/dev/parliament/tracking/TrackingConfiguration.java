package dev.parliament.tracking;

import com.fasterxml.jackson.databind.ObjectMapper;

import io.r2dbc.spi.ConnectionFactory;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.r2dbc.connection.R2dbcTransactionManager;
import org.springframework.r2dbc.core.DatabaseClient;
import org.springframework.transaction.reactive.TransactionalOperator;

@Configuration
@ConditionalOnProperty(prefix = "tracking", name = "enabled", havingValue = "true")
public class TrackingConfiguration {
    @Bean
    TrackingRepository trackingRepository(
            DatabaseClient db, ConnectionFactory factory, ObjectMapper mapper,dev.parliament.knowledge.KnowledgeIdentity identities) {
        return new TrackingRepository(
                db, TransactionalOperator.create(new R2dbcTransactionManager(factory)), mapper,identities);
    }

    @Bean
    TrackingDirectory trackingDirectory(DatabaseClient db, TrackingRepository repository,dev.parliament.knowledge.KnowledgeIdentity identities) {
        return new TrackingDirectory(db, repository,identities);
    }

    @Bean
    TrackingIssues trackingIssues() {
        return new TrackingIssues();
    }

    @Bean
    TrackingProjection trackingProjection(
            DatabaseClient db, TrackingRepository repository, ObjectMapper mapper,dev.parliament.knowledge.KnowledgeIdentity identities) {
        return new TrackingProjection(db, repository, mapper,identities);
    }

    @Bean
    TrackingAuthPolicy trackingAuthPolicy(
            @Value("${tracking.public-base-url:http://localhost:3000}") String url) {
        return new TrackingAuthPolicy(url);
    }

    @Bean
    TrackingAuthRepository trackingAuthRepository(
            DatabaseClient db,
            ConnectionFactory factory,
            TrackingRepository repository,
            ObjectMapper mapper,
            TrackingAuthPolicy policy,
            TrackingIssues issues,dev.parliament.knowledge.KnowledgeIdentity identities) {
        return new TrackingAuthRepository(
                db,
                repository,
                mapper,
                policy,
                java.time.Clock.systemUTC(),
                issues,
                TransactionalOperator.create(new R2dbcTransactionManager(factory)),identities);
    }

    @Bean
    TrackingDigests trackingDigests(
            DatabaseClient db,
            ConnectionFactory factory,
            TrackingRepository repository,
            TrackingAuthRepository auth,
            TrackingAuthPolicy policy,dev.parliament.knowledge.KnowledgeIdentity identities) {
        return new TrackingDigests(
                db,
                repository,
                auth,
                policy,
                TransactionalOperator.create(new R2dbcTransactionManager(factory)),identities);
    }

    @Bean
    TrackingAdminAuthorization trackingAdminAuthorization(
            @Value("${tracking.admin-key:}") String key) {
        return new TrackingAdminAuthorization(key);
    }

    @Bean(initMethod="initialize")
    dev.parliament.knowledge.KnowledgeIdentity knowledgeIdentity(DatabaseClient db,@Value("${knowledge.enabled:false}")boolean enabled) {
        return new dev.parliament.knowledge.KnowledgeIdentity(db,enabled);
    }
}
