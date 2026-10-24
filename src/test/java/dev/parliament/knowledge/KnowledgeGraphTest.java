package dev.parliament.knowledge;

import static dev.parliament.knowledge.KnowledgeBatch.*;
import static org.assertj.core.api.Assertions.*;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import dev.parliament.support.TestDatabase;
import dev.parliament.tracking.TrackingAdminAuthorization;
import dev.parliament.tracking.TrackingRepository;
import io.r2dbc.spi.ConnectionFactories;
import java.sql.DriverManager;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import org.junit.jupiter.api.*;
import org.springframework.core.io.ClassPathResource;
import org.springframework.jdbc.datasource.init.ScriptUtils;
import org.springframework.r2dbc.connection.R2dbcTransactionManager;
import org.springframework.r2dbc.core.DatabaseClient;
import org.springframework.test.web.reactive.server.WebTestClient;
import org.springframework.transaction.reactive.TransactionalOperator;

/** Only synthetic politicians are used in publication tests. */
class KnowledgeGraphTest {
    static TestDatabase mysql;
    DatabaseClient db;
    KnowledgeRepository repository;
    KnowledgeReads reads;
    KnowledgeGraphReads graphs;
    KnowledgeIdentity identities;

    @BeforeAll static void start() { mysql=TestDatabase.start("knowledge"); }
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

    @Test void draftsArePrivateAndAdminGraphRequiresAuthentication() {
        var b=KnowledgeFixtures.batch("graph_draft","pending","allowed");
        repository.importBatch(b).block();
        assertThatThrownBy(()->graphs.graph("p_test","person",2,40,null).block()).hasMessageContaining("404");
        var admin=WebTestClient.bindToController(new KnowledgeAdminController(repository,new TrackingAdminAuthorization("graph-fixture-key"),graphs)).build();
        admin.get().uri("/admin/tracking/knowledge/batches/graph_draft/graph").exchange().expectStatus().isForbidden();
        admin.get().uri("/admin/tracking/knowledge/batches/graph_draft/graph").header("X-Parliament-Ingestion-Key","graph-fixture-key")
                .exchange().expectStatus().isOk().expectBody().jsonPath("$.visibility").isEqualTo("candidate")
                .jsonPath("$.edges[0].evidenceIds").isArray();
    }

    @Test void publicationBuildsBoundedEvidenceBackedNeighborhoodAndPinsDocumentVersion() {
        var b=KnowledgeFixtures.batch("graph_published","approved","allowed");
        publish(b);
        var graph=graphs.graph("p_test","person",2,40,null).block();
        assertThat(graph.visibility()).isEqualTo("published");
        assertThat(graph.rootKey()).isEqualTo("person:p_test");
        assertThat(graph.nodes()).extracting(KnowledgeGraph.Node::key).contains("person:p_test","bill:b_test","document:doc_test");
        assertThat(graph.edges()).allSatisfy(e->assertThat(e.evidenceIds()).isNotEmpty());
        assertThat(graph.nodes().stream().filter(n->n.kind().equals("document")).findFirst().orElseThrow().href())
                .contains("version="+"a".repeat(64)).contains("extractionVersion=extract_v1");
        var api=WebTestClient.bindToController(new KnowledgeController(reads,graphs)).build();
        api.get().uri("/api/v1/knowledge/graph?rootId=p_test&rootKind=person&depth=0").exchange().expectStatus().isBadRequest();
        api.get().uri("/api/v1/knowledge/graph?rootId=p_test&rootKind=person&limit=101").exchange().expectStatus().isBadRequest();
        api.get().uri("/api/v1/knowledge/graph?rootId=p_test&rootKind=secret").exchange().expectStatus().isBadRequest();
    }

    @Test void newerPendingOrRejectedDecisionDoesNotResurrectAnOldApprovedEdge() {
        publish(lineage("graph_01","approved"));
        assertThat(graphs.graph("b_first","bill",1,40,"incorporated_into_alternative").block().edges()).hasSize(1);
        publish(lineage("graph_02","pending"));
        assertThat(graphs.graph("b_first","bill",1,40,"incorporated_into_alternative").block().edges()).isEmpty();
        publish(lineage("graph_03","rejected"));
        assertThat(graphs.graph("b_first","bill",1,40,"incorporated_into_alternative").block().edges()).isEmpty();
    }

    @Test void cyclesAndNodeLimitsTerminateWithoutDanglingEdges() {
        var b=lineage("graph_cycle","approved");
        var relations=new ArrayList<>(b.relations());
        relations.add(new Relation("cycle_back","b_second","b_first","incorporated_into_alternative",List.of("ev_test"),"approved","합성 순환 경계 검증"));
        publish(new KnowledgeBatch(b.id(),b.issueId(),b.entities(),b.documents(),b.evidence(),relations,List.of(),List.of()));
        var graph=graphs.graph("b_first","bill",2,2,null).block();
        assertThat(graph.nodes()).hasSize(2);
        assertThat(graph.truncated()).isTrue();
        assertThat(graph.edges()).allSatisfy(e->{
            assertThat(graph.nodes()).extracting(KnowledgeGraph.Node::key).contains(e.sourceKey(),e.targetKey());
        });
    }

    @Test void sourceScopedProfileRefreshRetainsOtherWikiFactsAndExplicitCorrectionWithdrawsItsOwnFacts() {
        var old=roster("profile_01","wiki_doc","biography","old",List.of(new Fact("소개","확인된 소개",List.of("wiki_evidence"))),List.of());
        publish(old);
        var current=roster("profile_02","roster_doc","current-roster","current",List.of(new Fact("현직","시험 장관",List.of("roster_evidence"))),
                List.of(new Tenure("org_fixture","시험 장관",null,null,null,KnowledgeFixtures.TIME,List.of("roster_evidence"))));
        publish(current);
        var profile=reads.profile("p_test").block();
        assertThat(profile.facts()).extracting(Fact::label).containsExactlyInAnyOrder("소개","현직");
        assertThat(profile.tenures()).hasSize(1);
        var withdrawn=roster("profile_03","roster_doc","current-roster","current",List.of(),List.of());
        publish(withdrawn);
        assertThat(reads.profile("p_test").block().facts()).extracting(Fact::label).containsExactly("소개");
        assertThat(reads.profile("p_test").block().tenures()).isEmpty();
    }

    @Test void tenureEdgesNeedUsableEvidenceAndUnpublishedDocumentsAreNotAdded() {
        publish(roster("tenure_allowed","roster_doc","current-roster","current",List.of(),
                List.of(new Tenure("org_fixture","시험 장관",null,null,null,KnowledgeFixtures.TIME,List.of("roster_evidence")))));
        var graph=graphs.graph("p_test","person",1,40,"holds_office").block();
        assertThat(graph.edges()).hasSize(1);
        assertThat(graph.edges().get(0).observedAt()).isEqualTo(KnowledgeFixtures.TIME);
        assertThat(graph.nodes()).extracting(KnowledgeGraph.Node::key).contains("organization:org_fixture");
        repository.importBatch(roster("unpublished","private_doc","private-source","private",List.of(),List.of())).block();
        assertThatThrownBy(()->graphs.graph("private_doc","document",1,40,null).block()).hasMessageContaining("404");
    }

    @Test void sameLiteralIdInDifferentKindsUsesSeparateNodeKeys() {
        var b=roster("same_id","p_test","current-roster","current",List.of(new Fact("성명","가상 의원",List.of("roster_evidence"))),List.of());
        publish(b);
        var graph=graphs.graph("p_test","person",1,40,null).block();
        assertThat(graph.nodes()).extracting(KnowledgeGraph.Node::key).contains("person:p_test","document:p_test");
        assertThat(graphs.graph("p_test","document",1,40,null).block().rootKey()).isEqualTo("document:p_test");
    }

    @Test void peopleCursorCanTraverseBeyondLegacyHundredAndFiltersTenureOrganizations() {
        publish(people("people_first",0,70));
        publish(people("people_second",70,40));
        var page=graphs.people(null,null,null,100).block();
        assertThat(page.items()).hasSize(100);
        assertThat(page.nextCursor()).isNotNull();
        var rest=graphs.people(page.nextCursor(),null,null,100).block();
        assertThat(rest.items()).hasSize(10);
        assertThat(rest.items()).extracting(KnowledgeGraph.Person::id).doesNotContainAnyElementsOf(page.items().stream().map(KnowledgeGraph.Person::id).toList());
        assertThat(graphs.people(null,"정치인 00","org_fixture",100).block().items()).hasSize(10)
                .allSatisfy(p->assertThat(p.organizationId()).isEqualTo("org_fixture"));
        assertThatThrownBy(()->graphs.people("invalid",null,null,20).block()).hasMessageContaining("cursor");
    }

    @Test void rootAliasesResolveToThePermanentPersonIdAndIssueEdgesRequirePublishedEvents() {
        publish(KnowledgeFixtures.batch("graph_alias","approved","allowed"));
        identities.alias("legacy_person","p_test").block();
        assertThat(graphs.graph("legacy_person","person",1,40,null).block().rootKey()).isEqualTo("person:p_test");
        var graph=graphs.graph("child-support-advance","issue",1,40,null).block();
        assertThat(graph.edges()).extracting(KnowledgeGraph.Edge::type).contains("in_issue");
        assertThat(graph.nodes()).extracting(KnowledgeGraph.Node::key).contains("activity:a_test");
    }

    @Test void unknownReuseRightsAreVisibleOnlyAsCandidateConnections() {
        var b=KnowledgeFixtures.batch("candidate_rights","pending","unknown");
        repository.importBatch(b).block();
        assertThat(graphs.candidate(b.id()).block().edges()).isNotEmpty();
        assertThatThrownBy(()->graphs.graph("doc_test","document",1,40,null).block()).hasMessageContaining("404");
        assertThatThrownBy(()->repository.review(b.id(),"publish","fixture-reviewer","미확인 자료").block()).isNotNull();
    }

    @Test void edgeCapProtectsDenseGraphsWithoutInventingNewNodes() {
        var b=people("dense_fixture",0,99);var entities=new ArrayList<Entity>();
        entities.add(b.entities().get(0));
        for(Entity person:b.entities().subList(1,b.entities().size())) {
            var tenures=new ArrayList<Tenure>();
            for(int role=0;role<11;role++)tenures.add(new Tenure("org_fixture","시험 직위 "+role,null,null,null,KnowledgeFixtures.TIME,person.tenures().get(0).evidenceIds()));
            entities.add(new Entity(person.id(),person.kind(),person.name(),person.identifiers(),person.facts(),tenures));
        }
        publish(new KnowledgeBatch(b.id(),b.issueId(),entities,b.documents(),b.evidence(),List.of(),List.of(),List.of()));
        var graph=graphs.graph("org_fixture","organization",1,100,null).block();
        assertThat(graph.nodes()).hasSize(100);
        assertThat(graph.edges()).hasSize(1000);
        assertThat(graph.truncated()).isTrue();
    }

    @Test void cursorIsBoundToSearchAndOrganizationAndDirectoryHttpRejectsInvalidLimits() {
        publish(people("cursor_fixture",0,5));
        var cursor=graphs.people(null,null,null,2).block().nextCursor();
        assertThatThrownBy(()->graphs.people(cursor,"다른 검색",null,2).block()).hasMessageContaining("cursor");
        assertThatThrownBy(()->graphs.people(cursor,null,"different_org",2).block()).hasMessageContaining("cursor");
        var api=WebTestClient.bindToController(new KnowledgeController(reads,graphs)).build();
        api.get().uri("/api/v1/knowledge/people?limit=2").exchange().expectStatus().isOk().expectBody()
                .jsonPath("$.items[0].observedAt").exists().jsonPath("$.nextCursor").isNotEmpty();
        api.get().uri("/api/v1/knowledge/people?limit=0").exchange().expectStatus().isBadRequest();
        api.get().uri("/api/v1/knowledge/graph?rootId=p_test&rootKind=person&relationType=invented").exchange().expectStatus().isBadRequest();
    }

    @Test void aPublishedLegacyPersonHasAnEmptyGraphInsteadOfLosingTheirExistingAddress() {
        db.sql("INSERT INTO parliament_person(identity_key,canonical_name,person_kind,resolution_status) VALUES('legacy-roster','합성 기존 의원','LEGISLATOR','RESOLVED')")
                .fetch().rowsUpdated().block();
        identities.initialize();
        String person=identities.forIdentity("legacy-roster").block();
        var graph=graphs.graph(person,"person",1,40,null).block();
        assertThat(graph.rootKey()).isEqualTo("person:"+person);
        assertThat(graph.nodes()).hasSize(1);
        assertThat(graph.edges()).isEmpty();
    }

    @Test void organizationFilterFindsAConcurrentOfficeInsteadOfOnlyTheFirstDisplayedOffice() {
        var b=roster("concurrent_office","roster_doc","current-roster","current",List.of(),List.of(
                new Tenure("org_fixture","시험 장관",null,null,null,KnowledgeFixtures.TIME,List.of("roster_evidence")),
                new Tenure("org_second","시험 위원장",null,null,null,KnowledgeFixtures.TIME.plusSeconds(60),List.of("roster_evidence"))));
        var entities=new ArrayList<>(b.entities());entities.add(new Entity("org_second","organization","합성 위원회",List.of(),List.of(),List.of()));
        publish(new KnowledgeBatch(b.id(),b.issueId(),entities,b.documents(),b.evidence(),List.of(),List.of(),List.of()));
        assertThat(graphs.people(null,null,"org_fixture",20).block().items()).hasSize(1)
                .allSatisfy(person->assertThat(person.position()).isEqualTo("시험 장관"));
    }

    @Test void revisionBudgetFailsExplicitlyInsteadOfReturningStaleApprovedConnections() {
        var seed=lineage("budget_seed","approved");var seedEntities=new ArrayList<>(seed.entities());
        var person=seedEntities.get(2);
        seedEntities.set(2,new Entity(person.id(),person.kind(),person.name(),person.identifiers(),person.facts(),List.of(
                new Tenure("org_budget","합성 직위",null,null,null,KnowledgeFixtures.TIME,List.of("ev_test")))));
        seedEntities.add(new Entity("org_budget","organization","상한 검증 기관",List.of(),List.of(),List.of()));
        publish(new KnowledgeBatch(seed.id(),seed.issueId(),seedEntities,seed.documents(),seed.evidence(),seed.relations(),seed.activities(),seed.contexts()));
        var mapper=new ObjectMapper().registerModule(new JavaTimeModule());var json=new KnowledgeJson(mapper);
        for(int i=0;i<KnowledgeGraphLimits.REVISIONS;i++) {
            String id="budget_revision_"+i;var batch=lineage(id,"rejected");
            db.sql("INSERT INTO knowledge_batch(batch_id,issue_id,payload_hash,payload,review_state,reviewed_at) VALUES(:id,:issue,:hash,:payload,'published',CURRENT_TIMESTAMP(6))")
                    .bind("id",id).bind("issue",batch.issueId()).bind("hash","0".repeat(64)).bind("payload",json.write(batch)).fetch().rowsUpdated().block();
            db.sql("INSERT INTO knowledge_entity_version(batch_id,entity_id,payload) VALUES(:batch,'b_first',:payload)")
                    .bind("batch",id).bind("payload",json.write(batch.entities().get(0))).fetch().rowsUpdated().block();
            db.sql("INSERT INTO knowledge_entity_version(batch_id,entity_id,payload) VALUES(:batch,'p_test',:payload)")
                    .bind("batch",id).bind("payload",json.write(batch.entities().get(2))).fetch().rowsUpdated().block();
        }
        assertThatThrownBy(()->graphs.graph("b_first","bill",1,40,null).block()).hasMessageContaining("503").hasMessageContaining("bounded read budget");
        assertThatThrownBy(()->reads.profile("p_test").block()).hasMessageContaining("503");
        // This root matches only the seed; the overflow is discovered by source revision closure.
        assertThatThrownBy(()->graphs.graph("org_budget","organization",1,40,null).block()).hasMessageContaining("503");
    }

    @Test void aDatedOfficeStatementIsHistoricalEvidenceAndNotAConfirmedCurrentOffice() {
        var b=roster("dated_statement","roster_doc","dated-source","statement",List.of(
                new Fact("명부 현재성","source_dated_office_statement",List.of("roster_evidence"))),List.of(
                new Tenure("org_fixture","발표 당시 직위",null,null,null,KnowledgeFixtures.TIME,List.of("roster_evidence"))));
        publish(b);
        var person=graphs.people(null,null,null,20).block().items().get(0);
        assertThat(person.position()).isNull();assertThat(person.organizationId()).isNull();
        assertThat(person.observedAt()).isEqualTo(KnowledgeFixtures.TIME);
        assertThat(graphs.people(null,null,"org_fixture",20).block().items()).isEmpty();
        assertThat(graphs.graph("p_test","person",1,40,"holds_office").block().edges()).hasSize(1);
    }

    @Test void aReviewedIssueOutsideTheLegacyCatalogCanStillBeExplored() {
        var b=KnowledgeFixtures.batch("new_issue","approved","allowed");
        publish(new KnowledgeBatch(b.id(),"operator-selected-fixture",b.entities(),b.documents(),b.evidence(),b.relations(),b.activities(),b.contexts()));
        assertThat(graphs.graph("operator-selected-fixture","issue",1,40,null).block().nodes())
                .extracting(KnowledgeGraph.Node::key).contains("issue:operator-selected-fixture","activity:a_test");
    }

    @Test void organizationRootIncludesANewerOfficeCorrectionEvenWhenThatBatchOmitsTheOldOrganization() {
        var old=roster("old_office","roster_doc","current-roster","current",List.of(),List.of(
                new Tenure("org_fixture","시험 장관",null,null,null,KnowledgeFixtures.TIME,List.of("roster_evidence"))));
        publish(old);
        var d=old.documents().get(0);
        var replacement=new Document("revised_doc",d.version(),d.sourceKey(),d.recordKey(),d.sourceUrl(),d.title(),d.format(),d.bodyStatus(),d.licenseStatus(),
                d.publishedAt(),d.collectedAt(),d.rawStorageKey(),d.extractionVersion(),d.segments(),"revised_observation",d.datePrecision());
        var revisedEvidence=new Evidence("revised_evidence",replacement.id(),replacement.version(),replacement.extractionVersion(),"roster_segment",0,5);
        var revised=new KnowledgeBatch("new_office",old.issueId(),List.of(
                new Entity("p_test","person","가상 의원",List.of(),List.of(),List.of(new Tenure("org_second","시험 장관",null,null,null,KnowledgeFixtures.TIME,List.of(revisedEvidence.id())))),
                new Entity("org_second","organization","합성 새 기관",List.of(),List.of(),List.of())),List.of(replacement),List.of(revisedEvidence),List.of(),List.of(),List.of());
        publish(revised);
        assertThat(graphs.graph("p_test","person",1,40,"holds_office").block().edges()).extracting(KnowledgeGraph.Edge::targetKey)
                .containsExactly("organization:org_second");
        assertThat(graphs.graph("org_fixture","organization",1,40,"holds_office").block().edges()).isEmpty();
    }

    @org.junit.jupiter.params.ParameterizedTest
    @org.junit.jupiter.params.provider.ValueSource(strings={"pending","rejected"})
    void oldDocumentRootCannotResurrectARelationshipWithdrawnUsingANewDocument(String decision) {
        publish(lineage("document_01","approved"));
        var original=lineage("document_02",decision);var json=new KnowledgeJson(new ObjectMapper().registerModule(new JavaTimeModule()));
        var tree=(com.fasterxml.jackson.databind.node.ObjectNode)json.tree(original);
        var doc=(com.fasterxml.jackson.databind.node.ObjectNode)tree.path("documents").get(0);
        doc.put("id","new_relationship_document").put("observationId","new_relationship_observation");
        var span=(com.fasterxml.jackson.databind.node.ObjectNode)tree.path("evidence").get(0);
        span.put("documentId","new_relationship_document");
        var revised=json.read(json.write(tree).replace("ev_test","new_relationship_evidence"),KnowledgeBatch.class);
        publish(revised);
        assertThat(graphs.graph("b_first","bill",1,40,null).block().edges()).extracting(KnowledgeGraph.Edge::type)
                .doesNotContain("incorporated_into_alternative");
        assertThat(graphs.graph("doc_test","document",1,40,null).block().edges()).extracting(KnowledgeGraph.Edge::type)
                .doesNotContain("incorporated_into_alternative");
    }

    @org.junit.jupiter.params.ParameterizedTest
    @org.junit.jupiter.params.provider.ValueSource(strings={"source_profile","source_rendered_profile","source_dated_acting_statement"})
    void sourceCurrentnessDistinguishesRenderedProfilesFromDatedActingStatements(String marker) {
        publish(roster("currentness_marker","roster_doc","current-roster","current",List.of(new Fact("명부 현재성",marker,List.of("roster_evidence"))),List.of(
                new Tenure("org_fixture","합성 직위",null,null,null,KnowledgeFixtures.TIME,List.of("roster_evidence")))));
        var person=graphs.people(null,null,null,20).block().items().get(0);
        assertThat(person.position()).isEqualTo(marker.equals("source_dated_acting_statement")?null:"합성 직위");
    }

    @Test void speakerAndDocumentRecordTargetsRemainActivitiesWhenABillSharesTheSameLiteralId() {
        var b=KnowledgeFixtures.batch("kind_collision","approved","allowed");var a=b.activities().get(0);
        var event=new dev.parliament.tracking.Activity("b_test",a.type(),a.title(),a.summary(),a.stage(),a.personIds(),a.topics(),a.billId(),
                a.occurredAt(),a.publishedAt(),a.collectedAt(),a.sourceUrl(),a.evidence(),a.votes(),a.coverage(),a.corrected(),a.version());
        var speaker=new Relation("speaker_role","p_test",event.id(),"speaker",List.of("ev_test"),"approved","합성 발언 역할");
        var record=new Relation("record_role","doc_test",event.id(),"records",List.of("ev_test"),"approved","합성 사건 기록");
        publish(new KnowledgeBatch(b.id(),b.issueId(),b.entities(),b.documents(),b.evidence(),List.of(speaker,record),List.of(event),
                List.of(new Context(event.id(),event.version(),List.of(speaker.id(),record.id()),List.of("ev_test"),List.of("doc_test"),"new_record"))));
        var graph=graphs.graph("p_test","person",2,40,null).block();
        assertThat(graph.edges().stream().filter(e->e.type().equals("speaker")||e.type().equals("records")))
                .hasSize(2).allSatisfy(edge->assertThat(edge.targetKey()).isEqualTo("activity:b_test"));
    }

    private void publish(KnowledgeBatch batch) {
        repository.importBatch(batch).block();
        repository.review(batch.id(),"publish","fixture-reviewer","합성 자료 검수").block();
    }
    private KnowledgeBatch lineage(String id,String decision) {
        var b=KnowledgeFixtures.batch(id,"approved","allowed");
        return new KnowledgeBatch(id,b.issueId(),List.of(new Entity("b_first","bill","원안",List.of(),List.of(),List.of()),new Entity("b_second","bill","대안",List.of(),List.of(),List.of()),b.entities().get(0)),b.documents(),b.evidence(),
                List.of(new Relation("lineage","b_first","b_second","incorporated_into_alternative",List.of("ev_test"),decision,"합성 대안 관계")),List.of(),List.of());
    }
    private KnowledgeBatch roster(String id,String documentId,String source,String record,List<Fact> facts,List<Tenure> tenures) {
        String evidenceId=source.equals("biography")?"wiki_evidence":"roster_evidence";
        if(source.equals("private-source"))evidenceId="private_evidence";
        var d=new Document(documentId,"b".repeat(64),source,record,"https://assembly.go.kr/fixture-roster","합성 명부","html","available","allowed",
                KnowledgeFixtures.TIME,KnowledgeFixtures.TIME,"raw/fixture/roster.html","extract_roster",List.of(new Segment("roster_segment","가상 의원 시험 장관 합성 자료","html:p=1",
                        List.of(new Mention("roster_name","가상 의원",0,5,List.of("p_test"),"p_test","approved")))),"observation_"+documentId,"second");
        var e=new Evidence(evidenceId,d.id(),d.version(),d.extractionVersion(),"roster_segment",0,5);
        return new KnowledgeBatch(id,"current-politicians",List.of(new Entity("p_test","person","가상 의원",List.of(),facts,tenures),new Entity("org_fixture","organization","합성 기관",List.of(),List.of(),List.of())),List.of(d),List.of(e),List.of(),List.of(),List.of());
    }
    private KnowledgeBatch people(String id,int from,int size) {
        var b=roster(id,"roster_doc","current-roster","current",List.of(),List.of());
        String text=java.util.stream.IntStream.range(0,110).mapToObj(i->"정치인 "+String.format("%03d",i)).collect(java.util.stream.Collectors.joining("\n"));
        String evidenceId="people_evidence_"+id;var mentions=new ArrayList<Mention>();
        var entities=new ArrayList<Entity>();entities.add(b.entities().get(1));
        for(int i=from;i<from+size;i++) {
            String personId="person_"+String.format("%03d",i),name="정치인 "+String.format("%03d",i);int start=text.indexOf(name);
            mentions.add(new Mention("name_"+i,name,start,start+name.length(),List.of(personId),personId,"approved"));
            entities.add(new Entity(personId,"person",name,List.of(),List.of(),
                    List.of(new Tenure("org_fixture","시험 직위",null,null,null,KnowledgeFixtures.TIME,List.of(evidenceId)))));
        }
        var d=b.documents().get(0);
        var doc=new Document(d.id(),d.version(),d.sourceKey(),d.recordKey(),d.sourceUrl(),d.title(),d.format(),d.bodyStatus(),d.licenseStatus(),
                d.publishedAt(),d.collectedAt(),d.rawStorageKey(),"extract_"+id,List.of(new Segment("people_segment",text,"html:p=1",mentions)),d.observationId(),d.datePrecision());
        var evidence=new Evidence(evidenceId,doc.id(),doc.version(),doc.extractionVersion(),"people_segment",0,text.length());
        return new KnowledgeBatch(id,b.issueId(),entities,List.of(doc),List.of(evidence),List.of(),List.of(),List.of());
    }
}
