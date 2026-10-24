package dev.parliament.knowledge;

import com.fasterxml.jackson.databind.ObjectMapper;
import dev.parliament.tracking.TrackingRepository;
import io.r2dbc.spi.ConnectionFactory;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.*;
import org.springframework.r2dbc.core.DatabaseClient;
import org.springframework.r2dbc.connection.R2dbcTransactionManager;
import org.springframework.transaction.reactive.TransactionalOperator;

@Configuration
@ConditionalOnProperty(prefix="knowledge",name="enabled",havingValue="true")
public class KnowledgeConfiguration {
    @Bean IssueReadingCatalog issueReadingCatalog(ObjectMapper mapper,
            @org.springframework.beans.factory.annotation.Value("${knowledge.editorial-source:file:web/src/data/editorial-issues.json}") org.springframework.core.io.Resource source,
            @org.springframework.beans.factory.annotation.Value("${knowledge.reading-catalog:classpath:knowledge/issue-readings.json}") org.springframework.core.io.Resource catalog) {
        return new IssueReadingCatalog(mapper, catalog, source);
    }
    @Bean IssueReadingReads issueReadingReads(IssueReadingCatalog catalog, KnowledgeReads reads, ConnectionFactory factory) {
        var definition = new org.springframework.transaction.support.DefaultTransactionDefinition();
        definition.setReadOnly(true);
        definition.setIsolationLevel(org.springframework.transaction.TransactionDefinition.ISOLATION_REPEATABLE_READ);
        var snapshot = TransactionalOperator.create(new R2dbcTransactionManager(factory), definition);
        return new IssueReadingReads(catalog, reads, snapshot::transactional);
    }
    @Bean KnowledgeRepository knowledgeRepository(DatabaseClient db,ConnectionFactory factory,ObjectMapper mapper,TrackingRepository events,KnowledgeIdentity identities) {
        return new KnowledgeRepository(db,TransactionalOperator.create(new R2dbcTransactionManager(factory)),mapper,events,identities);
    }
    @Bean KnowledgeReads knowledgeReads(DatabaseClient db,ObjectMapper mapper,TrackingRepository events,KnowledgeIdentity identities) {return new KnowledgeReads(db,mapper,events,identities);}
    @Bean KnowledgeGraphReads knowledgeGraphReads(DatabaseClient db,ObjectMapper mapper,KnowledgeIdentity identities,KnowledgeRepository repository) {return new KnowledgeGraphReads(db,mapper,identities,repository);}
}
