package dev.parliament.knowledge;

import static dev.parliament.knowledge.KnowledgeBatch.*;
import static org.assertj.core.api.Assertions.*;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import dev.parliament.support.TestDatabase;
import dev.parliament.tracking.TrackingRepository;
import io.r2dbc.spi.ConnectionFactories;
import java.sql.DriverManager;
import java.util.List;
import org.junit.jupiter.api.*;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;
import org.springframework.core.io.ClassPathResource;
import org.springframework.jdbc.datasource.init.ScriptUtils;
import org.springframework.r2dbc.connection.R2dbcTransactionManager;
import org.springframework.r2dbc.core.DatabaseClient;
import org.springframework.transaction.reactive.TransactionalOperator;

/** Publication tests use a separate database and synthetic roster people only. */
class KnowledgePublicationTest {
    static TestDatabase mysql;
    DatabaseClient db;
    KnowledgeRepository repository;
    KnowledgeReads reads;
    KnowledgeGraphReads graphs;
    KnowledgeIdentity identities;

    @BeforeAll static void start() { mysql=TestDatabase.start("knowledge-publication"); }
    @AfterAll static void stop() { if(mysql!=null)mysql.close(); }
    @BeforeEach void setup() throws Exception {
        try(var c=DriverManager.getConnection(mysql.jdbcUrl(),mysql.username(),mysql.password())) {
            for(String script:List.of("sql/migrations/015-knowledge-relations-down.sql","sql/migrations/014-knowledge-documents-down.sql","sql/migrations/013-knowledge-entities-down.sql","sql/migrations/010-tracking-down.sql","sql/reset-parliament.sql","sql/schema-parliament.sql","sql/schema-tracking.sql","sql/schema-knowledge.sql"))
                ScriptUtils.executeSqlScript(c,new ClassPathResource(script));
        }
        var factory=ConnectionFactories.get(io.r2dbc.spi.ConnectionFactoryOptions.parse(mysql.r2dbcUrl()).mutate()
                .option(io.r2dbc.spi.ConnectionFactoryOptions.USER,mysql.username())
                .option(io.r2dbc.spi.ConnectionFactoryOptions.PASSWORD,mysql.password()).build());
        db=DatabaseClient.create(factory);
        var tx=TransactionalOperator.create(new R2dbcTransactionManager(factory));
        var mapper=new ObjectMapper().registerModule(new JavaTimeModule());
        identities=new KnowledgeIdentity(db,true);
        var tracking=new TrackingRepository(db,tx,mapper,identities);
        repository=new KnowledgeRepository(db,tx,mapper,tracking,identities);
        reads=new KnowledgeReads(db,mapper,tracking,identities);
        graphs=new KnowledgeGraphReads(db,mapper,identities,repository);
    }

    @ParameterizedTest @CsvSource({"unknown,approved", "restricted,approved", "allowed,pending", "allowed,rejected"})
    void rosterOnlyPublicationCannotBypassRightsOrIdentityReview(String license,String identityDecision) {
        var b=roster(license,identityDecision);
        repository.importBatch(b).block();
        assertThatThrownBy(()->repository.review(b.id(),"publish","fixture-reviewer","합성 명부 검수").block())
                .isInstanceOf(IllegalArgumentException.class);
        assertThat(repository.get(b.id()).block().state()).isEqualTo("draft");
        assertPrivate();
        assertThat(graphs.candidate(b.id()).block().visibility()).isEqualTo("candidate");
    }

    @Test void approvedIdentityAndAllowedRosterClaimsPublishTogether() {
        var b=roster("allowed","approved");
        repository.importBatch(b).block();
        repository.review(b.id(),"publish","fixture-reviewer","합성 명부 검수").block();
        assertThat(graphs.people(null,null,null,20).block().items()).singleElement()
                .satisfies(person->assertThat(person.position()).isEqualTo("시험 장관"));
        assertThat(reads.profile("p_test").block().facts()).hasSize(1);
        assertThat(graphs.graph("p_test","person",1,40,"holds_office").block().edges()).hasSize(1);
    }

    @Test void emptyClaimsDoNotTurnAnExplicitPendingIdentityIntoAPublicPerson() {
        var b=roster("allowed","pending");
        var p=b.entities().get(0);
        b=new KnowledgeBatch(b.id(),b.issueId(),List.of(new Entity(p.id(),p.kind(),p.name(),p.identifiers(),List.of(),List.of()),b.entities().get(1)),
                b.documents(),b.evidence(),List.of(),List.of(),List.of());
        repository.importBatch(b).block();
        assertThatThrownBy(()->repository.review("roster_publication","publish","fixture-reviewer","빈 주장 우회").block())
                .isInstanceOf(IllegalArgumentException.class).hasMessageContaining("identity");
        assertPrivate();
    }

    @Test void legacyEmptyEntitiesWithoutCandidateIdentityOrClaimsKeepTheirPublicIdContract() {
        db.sql("INSERT INTO parliament_person(identity_key,canonical_name,person_kind,resolution_status) VALUES('legacy-fixture','합성 기존 인물','LEGISLATOR','RESOLVED')")
                .fetch().rowsUpdated().block();
        identities.initialize();
        String legacyId=identities.forIdentity("legacy-fixture").block();
        var b=new KnowledgeBatch("legacy_empty","current-politicians",List.of(
                new Entity(legacyId,"person","합성 기존 인물",List.of(),List.of(),List.of())),
                List.of(),List.of(),List.of(),List.of(),List.of());
        repository.importBatch(b).block();
        repository.review(b.id(),"publish","fixture-reviewer","기존 주소 계약 검수").block();
        assertThat(graphs.people(null,null,null,20).block().items()).extracting(KnowledgeGraph.Person::id).containsExactly(legacyId);
        assertThat(graphs.graph(legacyId,"person",1,40,null).block().edges()).isEmpty();
    }

    @Test void removingEveryCandidateFieldDoesNotPublishANewPerson() {
        var b=new KnowledgeBatch("stripped_candidate","current-politicians",List.of(
                new Entity("p_test","person","가상 의원",List.of(),List.of(),List.of())),
                List.of(),List.of(),List.of(),List.of(),List.of());
        repository.importBatch(b).block();
        assertThatThrownBy(()->repository.review(b.id(),"publish","fixture-reviewer","후보 필드 삭제 우회").block())
                .isInstanceOf(IllegalArgumentException.class).hasMessageContaining("identity");
        assertPrivate();
    }

    @ParameterizedTest @CsvSource({"changed_name", "new_identifier"})
    void aKnownPublicIdCannotIntroduceUnreviewedIdentityChanges(String change) {
        var approved=roster("allowed","approved");
        repository.importBatch(approved).block();
        repository.review(approved.id(),"publish","fixture-reviewer","신원 검수").block();
        var p=approved.entities().get(0);
        var changed=new Entity(p.id(),p.kind(),change.equals("changed_name")?"다른 인물":p.name(),
                change.equals("new_identifier")?List.of(new Identifier("UNVERIFIED_ID","unreviewed")):List.of(),List.of(),List.of());
        var b=new KnowledgeBatch("identity_change","current-politicians",List.of(changed),List.of(),List.of(),List.of(),List.of(),List.of());
        repository.importBatch(b).block();
        assertThatThrownBy(()->repository.review(b.id(),"publish","fixture-reviewer","기존 ID 우회").block())
                .isInstanceOf(IllegalArgumentException.class).hasMessageContaining("identity");
        assertThat(reads.profile(p.id()).block().name()).isEqualTo(p.name());
        assertThat(db.sql("SELECT COUNT(*) AS n FROM knowledge_identifier WHERE namespace='UNVERIFIED_ID'")
                .map((r,m)->r.get("n",Long.class)).one().block()).isZero();
    }

    @Test void unchangedPublishedIdentifiersCanBeReusedWithoutClearingWikiFacts() {
        var first=roster("allowed","approved");
        repository.importBatch(first).block();repository.review(first.id(),"publish","fixture-reviewer","기존 신원 검수").block();
        var p=first.entities().get(0);
        var b=new KnowledgeBatch("unchanged_identity",first.issueId(),List.of(new Entity(p.id(),p.kind(),p.name(),p.identifiers(),List.of(),List.of())),
                List.of(),List.of(),List.of(),List.of(),List.of());
        repository.importBatch(b).block();repository.review(b.id(),"publish","fixture-reviewer","기존 식별자 재사용").block();
        assertThat(reads.profile(p.id()).block().facts()).hasSize(1);
        assertThat(reads.profile(p.id()).block().tenures()).hasSize(1);
    }

    @Test void anUnknownEmptySourceSnapshotCannotWithdrawPreviouslyReviewedFacts() {
        var first=roster("allowed","approved");
        repository.importBatch(first).block();repository.review(first.id(),"publish","fixture-reviewer","신원과 사실 검수").block();
        var next=roster("unknown","pending");var p=next.entities().get(0);var d=next.documents().get(0);
        var unknown=new Document(d.id(),"b".repeat(64),d.sourceKey(),d.recordKey(),d.sourceUrl(),d.title(),d.format(),d.bodyStatus(),d.licenseStatus(),
                d.publishedAt(),d.collectedAt(),"raw/fixture/b.pdf",d.extractionVersion(),
                List.of(new Segment("seg_test",d.segments().get(0).text(),"pdf:page=1",List.of())),"next_observation",d.datePrecision());
        var b=new KnowledgeBatch("unknown_withdrawal",next.issueId(),List.of(new Entity(p.id(),p.kind(),p.name(),p.identifiers(),List.of(),List.of())),
                List.of(unknown),List.of(),List.of(),List.of(),List.of());
        repository.importBatch(b).block();
        assertThatThrownBy(()->repository.review(b.id(),"publish","fixture-reviewer","미확인 철회 우회").block())
                .isInstanceOf(IllegalArgumentException.class).hasMessageContaining("identity");
        assertThat(reads.profile(p.id()).block().facts()).hasSize(1);
    }

    @Test void aReviewedEmptySnapshotWithdrawsOnlyItsOwnIdentityReviewedSources() {
        var first=roster("allowed","approved");
        repository.importBatch(first).block();repository.review(first.id(),"publish","fixture-reviewer","기존 사실 검수").block();
        var d=first.documents().get(0);var p=first.entities().get(0);
        var reviewed=new Document("new_roster_doc",d.version(),"new-roster","record",d.sourceUrl(),d.title(),d.format(),d.bodyStatus(),"allowed",
                d.publishedAt(),d.collectedAt(),d.rawStorageKey(),d.extractionVersion(),d.segments(),"new_roster_observation",d.datePrecision());
        var unrelated=new Document("unrelated_doc",d.version(),d.sourceKey(),d.recordKey(),d.sourceUrl(),d.title(),d.format(),d.bodyStatus(),"unknown",
                d.publishedAt(),d.collectedAt(),d.rawStorageKey(),d.extractionVersion(),
                List.of(new Segment("seg_test",d.segments().get(0).text(),"pdf:page=1",List.of())),"unrelated_observation",d.datePrecision());
        var evidence=new Evidence("reviewed_identity",reviewed.id(),reviewed.version(),reviewed.extractionVersion(),"seg_test",0,5);
        var b=new KnowledgeBatch("scoped_withdrawal",first.issueId(),List.of(new Entity(p.id(),p.kind(),p.name(),p.identifiers(),List.of(),List.of())),
                List.of(reviewed,unrelated),List.of(evidence),List.of(),List.of(),List.of());
        repository.importBatch(b).block();repository.review(b.id(),"publish","fixture-reviewer","신원 근거 출처만 철회").block();
        assertThat(reads.profile(p.id()).block().facts()).hasSize(1);
    }

    private void assertPrivate() {
        assertThat(graphs.people(null,null,null,20).block().items()).isEmpty();
        assertThatThrownBy(()->graphs.graph("p_test","person",1,40,null).block()).hasMessageContaining("404");
        assertThatThrownBy(()->reads.profile("p_test").block()).hasMessageContaining("404");
        assertThatThrownBy(()->reads.document("doc_test",null).block()).hasMessageContaining("404");
        for(String table:List.of("knowledge_entity","knowledge_identifier","knowledge_identity_binding","knowledge_public_alias"))
            assertThat(db.sql("SELECT COUNT(*) AS n FROM "+table).map((r,m)->r.get("n",Long.class)).one().block()).isZero();
    }

    private KnowledgeBatch roster(String license,String identityDecision) {
        var b=KnowledgeFixtures.batch("roster_publication",identityDecision,license);
        if(identityDecision.equals("pending")) {
            var d=b.documents().get(0);var s=d.segments().get(0);var m=s.mentions().get(0);
            var mention=new Mention(m.id(),m.surface(),m.start(),m.end(),m.candidatePersonIds(),null,m.decision());
            b=KnowledgeFixtures.documents(b,List.of(new Document(d.id(),d.version(),d.sourceKey(),d.recordKey(),d.sourceUrl(),d.title(),d.format(),d.bodyStatus(),d.licenseStatus(),
                    d.publishedAt(),d.collectedAt(),d.rawStorageKey(),d.extractionVersion(),List.of(new Segment(s.id(),s.text(),s.locator(),List.of(mention))),d.observationId(),d.datePrecision())));
        }
        var p=b.entities().get(0);
        var person=new Entity(p.id(),p.kind(),p.name(),p.identifiers(),p.facts(),List.of(
                new Tenure("org_fixture","시험 장관",null,null,null,KnowledgeFixtures.TIME,List.of("ev_test"))));
        return new KnowledgeBatch(b.id(),"current-politicians",List.of(person,
                new Entity("org_fixture","organization","합성 기관",List.of(),List.of(),List.of())),
                b.documents(),b.evidence(),List.of(),List.of(),List.of());
    }
}
