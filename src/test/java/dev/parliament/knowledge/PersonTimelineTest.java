package dev.parliament.knowledge;

import static org.assertj.core.api.Assertions.*;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import dev.parliament.support.TestDatabase;
import dev.parliament.tracking.TrackingRepository;
import io.r2dbc.spi.ConnectionFactories;
import io.r2dbc.spi.ConnectionFactoryOptions;
import java.sql.DriverManager;
import java.util.List;
import org.junit.jupiter.api.*;
import org.springframework.core.io.ClassPathResource;
import org.springframework.jdbc.datasource.init.ScriptUtils;
import org.springframework.r2dbc.core.DatabaseClient;
import org.springframework.r2dbc.connection.R2dbcTransactionManager;
import org.springframework.transaction.reactive.TransactionalOperator;

class PersonTimelineTest {
    static TestDatabase mysql;
    KnowledgeRepository repository;
    KnowledgeReads reads;
    KnowledgeJson json;
    @BeforeAll static void start() { mysql=TestDatabase.start("person_timeline"); }
    @AfterAll static void stop() { if(mysql!=null)mysql.close(); }
    @BeforeEach void setup() throws Exception {
        try(var connection=DriverManager.getConnection(mysql.jdbcUrl(),mysql.username(),mysql.password())) {
            for(var script:List.of("sql/migrations/015-knowledge-relations-down.sql","sql/migrations/014-knowledge-documents-down.sql","sql/migrations/013-knowledge-entities-down.sql","sql/migrations/010-tracking-down.sql","sql/reset-parliament.sql","sql/schema-parliament.sql","sql/schema-tracking.sql","sql/schema-knowledge.sql"))
                ScriptUtils.executeSqlScript(connection,new ClassPathResource(script));
        }
        var factory=ConnectionFactories.get(ConnectionFactoryOptions.parse(mysql.r2dbcUrl()).mutate()
                .option(ConnectionFactoryOptions.USER,mysql.username()).option(ConnectionFactoryOptions.PASSWORD,mysql.password()).build());
        var db=DatabaseClient.create(factory);
        var tx=TransactionalOperator.create(new R2dbcTransactionManager(factory));
        var mapper=new ObjectMapper().registerModule(new JavaTimeModule());json=new KnowledgeJson(mapper);
        var identity=new KnowledgeIdentity(db,true);var tracking=new TrackingRepository(db,tx,mapper,identity);
        repository=new KnowledgeRepository(db,tx,mapper,tracking,identity);reads=new KnowledgeReads(db,mapper,tracking,identity);
    }
    private void add(int number,String role,boolean publish) {
        String text=json.write(KnowledgeFixtures.batch("fixture","approved","allowed"))
            .replace("fixture\"","batch_person_"+number+"\"")
            .replace("a_test","event_"+number).replace("v_test","version_"+number)
            .replace("doc_test","doc_"+number).replace("ev_test","evidence_"+number)
            .replace("rel_test","relation_"+number).replace("observation_test","observation_"+number)
            .replace(KnowledgeFixtures.TIME.toString(),KnowledgeFixtures.TIME.plusSeconds(number*86400L).toString());
        var b=json.read(text,KnowledgeBatch.class);var r=b.relations().get(0);
        var relation=new KnowledgeBatch.Relation(r.id(),r.subjectId(),role.equals("lead_sponsor")?r.objectId():b.activities().get(0).id(),role,r.evidenceIds(),r.decision(),r.reason());
        b=new KnowledgeBatch(b.id(),b.issueId(),b.entities(),b.documents(),b.evidence(),List.of(relation),b.activities(),b.contexts());
        repository.importBatch(b).block();
        if(publish)repository.review(b.id(),"publish","fixture-reviewer","合成 test fixture").block();
    }
    @Test void paginatesBothDirectionsAndKeepsDraftsPrivate() {
        add(1,"lead_sponsor",true);add(2,"speaker",true);add(3,"lead_sponsor",true);add(4,"speaker",false);
        var first=reads.personTimeline("p_test",null,2,"newest",null,null,null).block();
        assertThat(first.items()).extracting(KnowledgeReads.PublicContext::eventId).containsExactly("event_3","event_2");
        assertThat(first.nextCursor()).isNotBlank();
        var next=reads.personTimeline("p_test",first.nextCursor(),2,"newest",null,null,null).block();
        assertThat(next.items()).extracting(KnowledgeReads.PublicContext::eventId).containsExactly("event_1");
        assertThat(next.nextCursor()).isNull();
        assertThat(reads.personTimeline("p_test",null,2,"oldest",null,null,null).block().items())
                .extracting(KnowledgeReads.PublicContext::eventId).containsExactly("event_1","event_2");
    }
    @Test void filtersOnApprovedRoleAndSeoulCalendarDays() {
        add(1,"lead_sponsor",true);add(2,"speaker",true);add(3,"lead_sponsor",true);
        var published=repository.get("batch_person_2").block().batch();
        assertThat(published.activities().get(0).occurredAt()).isEqualTo(KnowledgeFixtures.TIME.plusSeconds(2*86400L));
        assertThat(published.relations().get(0).type()).isEqualTo("speaker");
        assertThat(reads.personTimeline("p_test",null,20,"newest",null,null,"speaker").block().items())
                .extracting(KnowledgeReads.PublicContext::eventId).containsExactly("event_2");
        assertThat(reads.personTimeline("p_test",null,20,"newest","2024-07-13","2024-07-15","speaker").block().items())
                .extracting(KnowledgeReads.PublicContext::eventId).containsExactly("event_2");
        assertThat(reads.personTimeline("p_test",null,20,"newest","2025-01-01",null,null).block().items()).isEmpty();
    }
    @Test void rejectsUnknownPeopleInvalidBoundsAndCursorReuseAcrossFilters() {
        add(1,"lead_sponsor",true);add(2,"speaker",true);
        assertThatThrownBy(()->reads.personTimeline("p_missing",null,20,"newest",null,null,null).block()).hasMessageContaining("404");
        for(var bad:List.of("x","newest;DROP TABLE"))
            assertThatThrownBy(()->reads.personTimeline("p_test",null,20,bad,null,null,null).block()).isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(()->reads.personTimeline("p_test",null,101,"newest",null,null,null).block()).isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(()->reads.personTimeline("p_test",null,20,"newest","2026-02-30",null,null).block()).isInstanceOf(IllegalArgumentException.class);
        var cursor=reads.personTimeline("p_test",null,1,"newest",null,null,null).block().nextCursor();
        assertThatThrownBy(()->reads.personTimeline("p_test",cursor,1,"oldest",null,null,null).block()).isInstanceOf(IllegalArgumentException.class);
    }
}
