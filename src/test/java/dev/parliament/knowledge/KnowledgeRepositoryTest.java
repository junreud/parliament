package dev.parliament.knowledge;

import static org.assertj.core.api.Assertions.*;
import static dev.parliament.knowledge.KnowledgeBatch.*;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import dev.parliament.support.TestDatabase;
import dev.parliament.tracking.TrackingRepository;
import io.r2dbc.spi.ConnectionFactories;
import java.sql.DriverManager;
import java.util.List;
import reactor.core.publisher.Mono;
import org.junit.jupiter.api.*;
import org.springframework.core.io.ClassPathResource;
import org.springframework.jdbc.datasource.init.ScriptUtils;
import org.springframework.r2dbc.connection.R2dbcTransactionManager;
import org.springframework.r2dbc.core.DatabaseClient;
import org.springframework.transaction.reactive.TransactionalOperator;

class KnowledgeRepositoryTest {
    static TestDatabase mysql;
    DatabaseClient db;
    KnowledgeRepository repository;
    KnowledgeReads reads;
    KnowledgeIdentity identities;
    TrackingRepository tracking;
    @BeforeAll static void start() { mysql=TestDatabase.start("knowledge"); }
    @AfterAll static void stop() { if(mysql!=null)mysql.close(); }
    @BeforeEach void setup() throws Exception {
        try(var c=DriverManager.getConnection(mysql.jdbcUrl(),mysql.username(),mysql.password())) {
            for(String script:List.of("sql/migrations/015-knowledge-relations-down.sql","sql/migrations/014-knowledge-documents-down.sql","sql/migrations/013-knowledge-entities-down.sql","sql/migrations/010-tracking-down.sql","sql/reset-parliament.sql","sql/schema-parliament.sql","sql/schema-tracking.sql","sql/schema-knowledge.sql"))
                ScriptUtils.executeSqlScript(c,new ClassPathResource(script));
        }
        var factory=ConnectionFactories.get(io.r2dbc.spi.ConnectionFactoryOptions.parse(mysql.r2dbcUrl()).mutate()
                .option(io.r2dbc.spi.ConnectionFactoryOptions.USER,mysql.username())
                .option(io.r2dbc.spi.ConnectionFactoryOptions.PASSWORD,mysql.password()).build()); db=DatabaseClient.create(factory);
        var tx=TransactionalOperator.create(new R2dbcTransactionManager(factory));
        var mapper=new ObjectMapper().registerModule(new JavaTimeModule());
        identities=new KnowledgeIdentity(db,true);
        tracking=new TrackingRepository(db,tx,mapper,identities);
        repository=new KnowledgeRepository(db,tx,mapper,tracking,identities);
        reads=new KnowledgeReads(db,mapper,tracking,identities);
    }
    @Test void keepsDraftsPrivateAndPublishesOnlyExplicitlyApprovedActors() {
        var b=KnowledgeFixtures.batch("batch_test","approved","allowed");
        assertThat(repository.importBatch(b).block().replayed()).isFalse();
        assertThatThrownBy(()->reads.profile("p_test").block()).hasMessageContaining("404");
        repository.review(b.id(),"publish","fixture-reviewer","합성 검수").block();
        var saved=repository.get(b.id()).block().batch();
        var context=reads.context("a_test",saved.activities().get(0).version()).block();
        assertThat(context.participants()).hasSize(1);
        assertThat(context.participants().get(0).role()).isEqualTo("lead_sponsor");
        assertThat(reads.evidence("ev_test").block().excerpt()).isEqualTo("가상 의원");
        assertThat(reads.document("doc_test",null).block()).doesNotContainKey("rawStorageKey");
    }
    @Test void preservesImmutableImportsAndRecordsNewPollObservationsWithoutNewEvents() {
        var b=KnowledgeFixtures.batch("batch_test","approved","allowed");
        repository.importBatch(b).block();
        assertThat(repository.importBatch(b).block().replayed()).isTrue();
        var d=b.documents().get(0);
        var polled=new Document(d.id(),d.version(),d.sourceKey(),d.recordKey(),d.sourceUrl(),d.title(),d.format(),d.bodyStatus(),d.licenseStatus(),d.publishedAt(),d.collectedAt(),d.rawStorageKey(),d.extractionVersion(),d.segments(),"observation_second",d.datePrecision(),d.transitionId(),d.collectedAt().plusSeconds(60));
        assertThat(repository.importBatch(KnowledgeFixtures.documents(b,List.of(polled))).block().replayed()).isTrue();
        assertThat(db.sql("SELECT COUNT(*) AS n FROM knowledge_document_observation").map((r,m)->r.get("n",Long.class)).one().block()).isEqualTo(2);
        assertThat(db.sql("SELECT observed_at FROM knowledge_document_observation WHERE observation_id='observation_second'").map((r,m)->r.get("observed_at",java.time.Instant.class)).one().block())
                .isEqualTo(d.collectedAt().plusSeconds(60));
        var changed=new Entity("p_test","person","다른 이름",b.entities().get(0).identifiers(),b.entities().get(0).facts(),List.of());
        assertThatThrownBy(()->repository.importBatch(new KnowledgeBatch(b.id(),b.issueId(),List.of(changed,b.entities().get(1)),b.documents(),b.evidence(),b.relations(),b.activities(),b.contexts())).block()).hasMessageContaining("409");
    }
    @Test void rejectsPendingRolePublicationAtomically() {
        var b=KnowledgeFixtures.batch("batch_test","pending","allowed");
        repository.importBatch(b).block();
        assertThatThrownBy(()->repository.review(b.id(),"publish","fixture-reviewer","검수").block()).hasMessageContaining("participant");
        assertThat(repository.get(b.id()).block().state()).isEqualTo("draft");
    }
    @Test void storesAnExistingPublicIdInsteadOfRecomputingItOnRebuild() {
        db.sql("INSERT INTO parliament_person(identity_key,canonical_name,person_kind,resolution_status) VALUES('old-key','가상 의원','LEGISLATOR','RESOLVED')").fetch().rowsUpdated().block();
        identities.initialize();
        String old=identities.forIdentity("old-key").block();
        identities.bind("new-key",old,"verified-batch").block();
        assertThat(identities.forIdentity("new-key").block()).isEqualTo(old);
        assertThatThrownBy(()->identities.bind("new-key","p_other","verified-batch").block()).isNotNull();
    }
    @Test void cannotPublishKnowledgeActorsThroughTheGenericReviewPath() {
        var b=KnowledgeFixtures.batch("batch_test","pending","allowed");
        var imported=repository.importBatch(b).block();
        var a=imported.batch().activities().get(0);
        assertThatThrownBy(()->tracking.publish(a.id(),a.version(),"generic-admin","승인 우회").block())
                .hasMessageContaining("knowledge batch review");
        assertThat(tracking.feed(null,null,null,null,null,null,20).block().items()).isEmpty();
    }
    @Test void reviewExportCanApproveMentionsWithoutRewritingPhysicalExtraction() {
        repository.importBatch(KnowledgeFixtures.batch("batch_pending","pending","allowed")).block();
        var approved=KnowledgeFixtures.batch("batch_reviewed","approved","allowed");
        assertThatCode(()->repository.importBatch(approved).block()).doesNotThrowAnyException();
        repository.review(approved.id(),"publish","fixture-reviewer","개별 후보 검수").block();
        assertThat(reads.document("doc_test",null).block()).containsKey("segments");
    }
    @Test void concurrentImportsCannotReuseAnEvidenceIdForADifferentSpan() {
        var first=KnowledgeFixtures.batch("batch_first","approved","allowed");
        var second=KnowledgeFixtures.distinctEventAndDocument(first,"batch_second","a_second","doc_second");
        var e=second.evidence().get(0);
        second=new KnowledgeBatch(second.id(),second.issueId(),second.entities(),second.documents(),
                List.of(new Evidence(e.id(),e.documentId(),e.documentVersion(),e.extractionVersion(),e.segmentId(),6,10)),
                second.relations(),second.activities(),second.contexts());
        var outcomes=reactor.core.publisher.Flux.merge(
                repository.importBatch(first).map(x->"stored").onErrorResume(ex->Mono.just(ex.getMessage())),
                repository.importBatch(second).map(x->"stored").onErrorResume(ex->Mono.just(ex.getMessage())))
                .collectList().block();
        assertThat(outcomes).hasSize(2).contains("stored");
        assertThat(outcomes.stream().filter(x->x.contains("immutable span"))).hasSize(1);
        assertThat(db.sql("SELECT COUNT(*) AS n FROM knowledge_evidence_registry").map((r,m)->r.get("n",Long.class)).one().block()).isEqualTo(1);
        assertThat(db.sql("SELECT COUNT(*) AS n FROM knowledge_batch").map((r,m)->r.get("n",Long.class)).one().block()).isEqualTo(1);
    }
    @Test void serverDerivesActivityEvidenceInsteadOfTrustingSubmittedExcerpts() {
        var input=KnowledgeFixtures.batch("batch_test","approved","allowed");
        var imported=repository.importBatch(input).block().batch();
        assertThat(imported.activities().get(0).evidence().get(0).excerpt()).isEqualTo("가상 의원");
        assertThat(imported.activities().get(0).evidence().get(0).sourceVersion()).isEqualTo("a".repeat(64));
    }
    @Test void allPublicDirectoryPathsRequireThePublishedKnowledgeBatch() {
        var b=repository.importBatch(KnowledgeFixtures.batch("batch_test","approved","allowed")).block().batch();
        var a=b.activities().get(0);
        // Simulate a legacy/manual inconsistent DB row to verify public defense in depth.
        db.sql("UPDATE tracking_event_version SET review_state='published',reviewed_at=CURRENT_TIMESTAMP(6) WHERE event_id=:id")
                .bind("id",a.id()).fetch().rowsUpdated().block();
        db.sql("UPDATE tracking_event SET latest_version=:version WHERE event_id=:id")
                .bind("version",a.version()).bind("id",a.id()).fetch().rowsUpdated().block();
        assertThat(tracking.feed(null,null,null,null,null,null,20).block().items()).isEmpty();
        assertThatThrownBy(()->tracking.detail(a.id(),null).block()).hasMessageContaining("404");
        assertThat(tracking.history(a.id()).collectList().block()).isEmpty();
        assertThat(new dev.parliament.tracking.TrackingDirectory(db,tracking,identities).bills(null).collectList().block()).isEmpty();
    }
    @Test void preservesExistingPublishedBillIdsAndNewlyCollectedPersonIds() {
        var legacy=new TrackingRepository(db,org.springframework.transaction.reactive.TransactionalOperator.create(
                new R2dbcTransactionManager(db.getConnectionFactory())),new ObjectMapper().registerModule(new JavaTimeModule()));
        var a=KnowledgeFixtures.batch("legacy","approved","allowed").activities().get(0);
        legacy.importDraft(a).block();legacy.publish(a.id(),a.version(),"fixture-reviewer","").block();
        identities.initialize();
        assertThat(db.sql("SELECT entity_id FROM knowledge_entity WHERE entity_id='b_test'").fetch().one().block()).isNotNull();
        db.sql("INSERT INTO parliament_person(identity_key,canonical_name,person_kind,resolution_status) VALUES('new-after-startup','새 수집 인물','LEGISLATOR','RESOLVED')")
                .fetch().rowsUpdated().block();
        var people=new dev.parliament.tracking.TrackingDirectory(db,tracking,identities).people(null).collectList().block();
        assertThat(people).extracting(dev.parliament.tracking.TrackingDirectory.Person::id).contains("p_"+KnowledgeJson.hash("new-after-startup"));
        assertThat(identities.forIdentity("new-after-startup").block()).isEqualTo("p_"+KnowledgeJson.hash("new-after-startup"));
    }
    @Test void publicTimelinePaginatesAndPreservesOccurrenceVersusPublicationDates() {
        var b=KnowledgeFixtures.batch("batch_first","approved","allowed");
        var second=KnowledgeFixtures.distinctEventAndDocument(b,"batch_second","a_second","doc_second");
        var old=second.evidence().get(0);var e=new Evidence("ev_second",old.documentId(),old.documentVersion(),old.extractionVersion(),old.segmentId(),old.start(),old.end());
        var relation=new Relation("rel_second","p_test","b_test","lead_sponsor",List.of(e.id()),"approved","합성 표본");
        var a=second.activities().get(0);
        a=new dev.parliament.tracking.Activity(a.id(),a.type(),a.title(),null,a.stage(),a.personIds(),a.topics(),a.billId(),null,a.publishedAt().plusSeconds(3600),a.collectedAt(),a.sourceUrl(),a.evidence(),a.votes(),a.coverage(),false,a.version());
        second=new KnowledgeBatch(second.id(),second.issueId(),List.of(new Entity("p_test","person","가상 의원",List.of(),List.of(),List.of()),second.entities().get(1)),second.documents(),List.of(e),List.of(relation),List.of(a),
                List.of(new Context(a.id(),a.version(),List.of(relation.id()),List.of(e.id()),List.of("doc_second"),"new_record")));
        repository.importBatch(b).block();repository.review(b.id(),"publish","fixture-reviewer","검수").block();
        repository.importBatch(second).block();repository.review(second.id(),"publish","fixture-reviewer","검수").block();
        var first=reads.timeline(b.issueId(),null,1).block();
        assertThat(first.items()).hasSize(1);assertThat(first.items().get(0).dateKind()).isEqualTo("published");
        var next=reads.timeline(b.issueId(),first.nextCursor(),1).block();
        assertThat(next.items()).hasSize(1);assertThat(next.items().get(0).dateKind()).isEqualTo("occurred");assertThat(next.nextCursor()).isNull();
        assertThat(reads.profile("p_test").block().relatedIssues()).extracting(x->x.get("id")).containsExactly(b.issueId());
        assertThatThrownBy(()->reads.timeline(b.issueId(),"invalid",20).block()).hasMessageContaining("cursor");
    }
    @Test void publicDocumentPinsBothRawAndExtractionVersionsAndMetadataIsImmutable() {
        var b=KnowledgeFixtures.batch("batch_first","approved","allowed");
        repository.importBatch(b).block();repository.review(b.id(),"publish","fixture-reviewer","검수").block();
        var j=new KnowledgeJson(new ObjectMapper().registerModule(new JavaTimeModule()));
        var tree=(com.fasterxml.jackson.databind.node.ObjectNode)j.tree(b);tree.put("id","batch_second");
        var d=(com.fasterxml.jackson.databind.node.ObjectNode)tree.path("documents").get(0);
        d.put("title","정정된 합성 표본").put("extractionVersion","extract_v2").put("observationId","observation_second");
        var e=(com.fasterxml.jackson.databind.node.ObjectNode)tree.path("evidence").get(0);e.put("id","ev_second").put("extractionVersion","extract_v2");
        tree=(com.fasterxml.jackson.databind.node.ObjectNode)j.tree(j.read(j.write(tree).replace("ev_test","ev_second"),KnowledgeBatch.class));
        var changed=j.read(j.write(tree),KnowledgeBatch.class);
        repository.importBatch(changed).block();repository.review(changed.id(),"publish","fixture-reviewer","메타데이터 정정").block();
        assertThat(reads.document("doc_test","a".repeat(64),"extract_v1").block().get("title")).isEqualTo("합성 표본");
        assertThat(reads.document("doc_test","a".repeat(64),"extract_v2").block().get("title")).isEqualTo("정정된 합성 표본");
        assertThat(reads.document("doc_test",null,null).block().get("extractionVersion")).isEqualTo("extract_v2");
        assertThatThrownBy(()->reads.document("doc_test","a".repeat(64),"missing_extract").block()).hasMessageContaining("404");
        var altered=(com.fasterxml.jackson.databind.node.ObjectNode)j.tree(changed);altered.put("id","batch_tampered");
        ((com.fasterxml.jackson.databind.node.ObjectNode)altered.path("documents").get(0)).put("title","동일 추출 버전 변조");
        assertThatThrownBy(()->repository.importBatch(j.read(j.write(altered),KnowledgeBatch.class)).block()).hasMessageContaining("immutable extraction");
    }
    @Test void adminAndSixPublicHttpRoutesHonorTheSameContract() {
        var b=KnowledgeFixtures.batch("batch_test","approved","allowed");
        var admin=org.springframework.test.web.reactive.server.WebTestClient.bindToController(
                new KnowledgeAdminController(repository,new dev.parliament.tracking.TrackingAdminAuthorization("fixture-admin-key"))).build();
        admin.get().uri("/admin/tracking/knowledge/batches/batch_test").exchange().expectStatus().isForbidden();
        admin.post().uri("/admin/tracking/knowledge/batches").header("X-Parliament-Ingestion-Key","fixture-admin-key")
                .bodyValue(b).exchange().expectStatus().isOk().expectBody().jsonPath("$.state").isEqualTo("draft");
        admin.get().uri("/admin/tracking/knowledge/batches/batch_test").header("X-Parliament-Ingestion-Key","fixture-admin-key")
                .exchange().expectStatus().isOk().expectBody().jsonPath("$.batch.documents[0].rawStorageKey").exists();
        admin.post().uri("/admin/tracking/knowledge/batches/batch_test/review").header("X-Parliament-Ingestion-Key","fixture-admin-key")
                .bodyValue(new KnowledgeAdminController.Review("publish","fixture-reviewer","검수"))
                .exchange().expectStatus().isOk().expectBody().jsonPath("$.state").isEqualTo("published");
        var api=org.springframework.test.web.reactive.server.WebTestClient.bindToController(new KnowledgeController(reads)).build();
        api.get().uri("/api/v1/people/p_test/profile").exchange().expectStatus().isOk().expectBody().jsonPath("$.facts").isArray();
        api.get().uri("/api/v1/activities/a_test/context").exchange().expectStatus().isOk().expectBody().jsonPath("$.participants[0].role").isEqualTo("lead_sponsor");
        api.get().uri("/api/v1/documents/doc_test?version="+"a".repeat(64)+"&extractionVersion=extract_v1").exchange().expectStatus().isOk().expectBody().jsonPath("$.rawStorageKey").doesNotExist();
        api.get().uri("/api/v1/evidence/ev_test").exchange().expectStatus().isOk().expectBody().jsonPath("$.excerpt").isEqualTo("가상 의원");
        api.get().uri("/api/v1/bills/b_test/lineage").exchange().expectStatus().isOk().expectBody().jsonPath("$.items").isArray();
        api.get().uri("/api/v1/issues/child-support-advance/timeline?limit=1").exchange().expectStatus().isOk().expectBody().jsonPath("$.items[0].activity.id").isEqualTo("a_test");
        api.get().uri("/api/v1/issues/child-support-advance/timeline?limit=0").exchange().expectStatus().isBadRequest();
        api.get().uri("/api/v1/evidence/missing").exchange().expectStatus().isNotFound();
    }
    @org.junit.jupiter.params.ParameterizedTest
    @org.junit.jupiter.params.provider.ValueSource(strings={"explanation_only","extraction_only"})
    void nonFactualChangesNeverReceiveDigestItems(String changeKind) {
        var b=KnowledgeFixtures.batch("batch_test","approved","allowed");var c=b.contexts().get(0);
        b=new KnowledgeBatch(b.id(),b.issueId(),b.entities(),b.documents(),b.evidence(),b.relations(),b.activities(),
                List.of(new Context(c.eventId(),c.eventVersion(),c.relationIds(),c.evidenceIds(),c.documentIds(),changeKind)));
        repository.importBatch(b).block();repository.review(b.id(),"publish","fixture-reviewer","설명 변경").block();
        var mapper=new ObjectMapper().registerModule(new JavaTimeModule());var policy=new dev.parliament.tracking.TrackingAuthPolicy("http://localhost:3000");
        var tx=TransactionalOperator.create(new R2dbcTransactionManager(db.getConnectionFactory()));
        var auth=new dev.parliament.tracking.TrackingAuthRepository(db,tracking,mapper,policy,java.time.Clock.systemUTC(),new dev.parliament.tracking.TrackingIssues(),tx,identities);
        db.sql("INSERT INTO tracking_user(user_id,email,unsubscribe_hash,unsubscribe_token,email_enabled,verified_at) VALUES('fixture-user','fixture@example.test',:hash,:token,true,CURRENT_TIMESTAMP(6))")
                .bind("hash","b".repeat(64)).bind("token","c".repeat(43)).fetch().rowsUpdated().block();
        auth.replaceFollows("fixture-user",List.of(new dev.parliament.tracking.TrackingAuthRepository.Follow("person","p_test")),"weekly").block();
        var digest=new dev.parliament.tracking.TrackingDigests(db,tracking,auth,policy,tx,identities);
        assertThat(digest.build("weekly",java.time.Instant.now().minusSeconds(60),java.time.Instant.now().plusSeconds(60)).block().queued()).isZero();
        assertThat(db.sql("SELECT COUNT(*) AS n FROM tracking_digest_item").map((r,m)->r.get("n",Long.class)).one().block()).isZero();
        var disabled=new KnowledgeIdentity(db,false);disabled.initialize();
        assertThat(new dev.parliament.tracking.TrackingDigests(db,tracking,auth,policy,tx,disabled)
                .build("weekly",java.time.Instant.now().minusSeconds(60),java.time.Instant.now().plusSeconds(60)).block().queued()).isZero();
    }
    @Test void unknownTenureCanUseOnlyAnEventSpecificDatedObservation() {
        var b=withTenure(KnowledgeFixtures.TIME);
        repository.importBatch(b).block();repository.review(b.id(),"publish","fixture-reviewer","사건 당시 직위 근거").block();
        var participant=reads.context("a_test",null).block().participants().get(0);
        assertThat(participant.organizationAtTime()).isEqualTo("합성 기관");
        assertThat(participant.positionAtTime()).isEqualTo("시험 직위");
        assertThat(reads.profile("p_test").block().tenures().get(0).get("validFrom")).isNull();
    }
    @Test void currentPositionObservationCannotBeAppliedToAnOlderEvent() {
        var b=withTenure(KnowledgeFixtures.TIME.plusSeconds(365L*86400));
        repository.importBatch(b).block();repository.review(b.id(),"publish","fixture-reviewer","현재 관측").block();
        var participant=reads.context("a_test",null).block().participants().get(0);
        assertThat(participant.organizationAtTime()).isNull();assertThat(participant.positionAtTime()).isNull();
    }
    @Test void genericRejectCannotIsolateAKnowledgeBatchFromItsReviewFlow() {
        var b=repository.importBatch(KnowledgeFixtures.batch("batch_test","pending","allowed")).block().batch();var a=b.activities().get(0);
        assertThatThrownBy(()->tracking.reject(a.id(),a.version()).block()).hasMessageContaining("knowledge batch review");
        repository.review(b.id(),"reject","fixture-reviewer","후보 기각").block();
        assertThat(repository.get(b.id()).block().state()).isEqualTo("rejected");
        assertThatCode(()->repository.review(b.id(),"reject","fixture-reviewer","다시 확인").block()).doesNotThrowAnyException();
    }
    private KnowledgeBatch withTenure(java.time.Instant observedAt) {
        var b=KnowledgeFixtures.batch("batch_test","approved","allowed");var p=b.entities().get(0);
        var person=new Entity(p.id(),p.kind(),p.name(),p.identifiers(),p.facts(),List.of(new Tenure("org_fixture","시험 직위",null,null,null,observedAt,List.of("ev_test"))));
        return new KnowledgeBatch(b.id(),b.issueId(),List.of(person,b.entities().get(1),new Entity("org_fixture","organization","합성 기관",List.of(),List.of(),List.of())),
                b.documents(),b.evidence(),b.relations(),b.activities(),b.contexts());
    }
    @Test void approvedMentionWithoutAnActorRoleDoesNotEnterPersonActivityOrDigest() {
        var b=KnowledgeFixtures.batch("batch_test","approved","allowed");var d=b.documents().get(0);
        var mention=new Mention("mention_only","언급 인물",12,17,List.of("p_mentioned"),"p_mentioned","approved");
        var doc=new Document(d.id(),d.version(),d.sourceKey(),d.recordKey(),d.sourceUrl(),d.title(),d.format(),d.bodyStatus(),d.licenseStatus(),d.publishedAt(),d.collectedAt(),d.rawStorageKey(),d.extractionVersion(),
                List.of(new Segment("seg_test","가상 의원 대표발의. 언급 인물","pdf:page=1",List.of(d.segments().get(0).mentions().get(0),mention))),d.observationId(),d.datePrecision());
        var identityEvidence=new Evidence("ev_mentioned_identity",doc.id(),doc.version(),doc.extractionVersion(),"seg_test",12,17);
        b=new KnowledgeBatch(b.id(),b.issueId(),List.of(b.entities().get(0),b.entities().get(1),new Entity("p_mentioned","person","언급 인물",List.of(),List.of(),List.of())),
                List.of(doc),List.of(b.evidence().get(0),identityEvidence),b.relations(),b.activities(),b.contexts());
        repository.importBatch(b).block();repository.review(b.id(),"publish","fixture-reviewer","언급과 행동 구분").block();
        assertThat(reads.profile("p_mentioned").block().activities()).isEmpty();
        assertThat(tracking.feed("p_mentioned",null,null,null,null,null,20).block().items()).isEmpty();
        var mapper=new ObjectMapper().registerModule(new JavaTimeModule());var policy=new dev.parliament.tracking.TrackingAuthPolicy("http://localhost:3000");
        var tx=TransactionalOperator.create(new R2dbcTransactionManager(db.getConnectionFactory()));
        var auth=new dev.parliament.tracking.TrackingAuthRepository(db,tracking,mapper,policy,java.time.Clock.systemUTC(),new dev.parliament.tracking.TrackingIssues(),tx,identities);
        db.sql("INSERT INTO tracking_user(user_id,email,unsubscribe_hash,unsubscribe_token,email_enabled,verified_at) VALUES('fixture-user','fixture@example.test',:hash,:token,true,CURRENT_TIMESTAMP(6))")
                .bind("hash","b".repeat(64)).bind("token","c".repeat(43)).fetch().rowsUpdated().block();
        auth.replaceFollows("fixture-user",List.of(new dev.parliament.tracking.TrackingAuthRepository.Follow("person","p_mentioned")),"weekly").block();
        assertThat(new dev.parliament.tracking.TrackingDigests(db,tracking,auth,policy,tx,identities)
                .build("weekly",java.time.Instant.now().minusSeconds(60),java.time.Instant.now().plusSeconds(60)).block().queued()).isZero();
    }
    @Test void entireParagraphEvidenceUsesOnlyAdjacentTextFromItsPinnedExtraction() {
        var b=KnowledgeFixtures.batch("batch_first","approved","allowed");var d=b.documents().get(0);
        var doc=new Document(d.id(),d.version(),d.sourceKey(),d.recordKey(),d.sourceUrl(),d.title(),d.format(),d.bodyStatus(),d.licenseStatus(),d.publishedAt(),d.collectedAt(),d.rawStorageKey(),d.extractionVersion(),
                List.of(new Segment("before","앞 문단","pdf:page=1:paragraph=1",List.of()),d.segments().get(0),new Segment("after","뒤 문단","pdf:page=1:paragraph=3",List.of())),d.observationId(),d.datePrecision());
        var e=new Evidence("ev_test",d.id(),d.version(),d.extractionVersion(),"seg_test",0,10);
        b=new KnowledgeBatch(b.id(),b.issueId(),b.entities(),List.of(doc),List.of(e),b.relations(),b.activities(),b.contexts());
        repository.importBatch(b).block();repository.review(b.id(),"publish","fixture-reviewer","전체 문단 검수").block();
        assertThat(reads.evidence("ev_test").block().before()).contains("앞 문단");
        assertThat(reads.evidence("ev_test").block().after()).contains("뒤 문단");
        var j=new KnowledgeJson(new ObjectMapper().registerModule(new JavaTimeModule()));
        var newInput=j.read(j.write(b).replace("batch_first","batch_second").replace("a".repeat(64),"b".repeat(64)).replace("ev_test","ev_second").replace("observation_test","observation_second").replace("앞 문단","다음 버전 앞 문단").replace("뒤 문단","다음 버전 뒤 문단"),KnowledgeBatch.class);
        repository.importBatch(newInput).block();repository.review(newInput.id(),"publish","fixture-reviewer","새 원문").block();
        assertThat(reads.evidence("ev_test").block().before()).doesNotContain("다음 버전");
        assertThat(reads.evidence("ev_second").block().before()).contains("다음 버전");
    }
    @Test void disablingKnowledgeKeepsDurableAddressesFeedsAndFollowsAfterRebuild() {
        db.sql("INSERT INTO parliament_person(identity_key,canonical_name,person_kind,resolution_status) VALUES('before-rebuild','가상 의원','LEGISLATOR','RESOLVED')").fetch().rowsUpdated().block();
        identities.initialize();String stable=identities.forIdentity("before-rebuild").block();
        identities.bind("after-rebuild",stable,"verified-rebuild").block();
        db.sql("DELETE FROM parliament_person WHERE identity_key='before-rebuild'").fetch().rowsUpdated().block();
        db.sql("INSERT INTO parliament_person(identity_key,canonical_name,person_kind,resolution_status) VALUES('after-rebuild','가상 의원','LEGISLATOR','RESOLVED')").fetch().rowsUpdated().block();
        var mapper=new ObjectMapper().registerModule(new JavaTimeModule());var json=new KnowledgeJson(mapper);
        var tree=(com.fasterxml.jackson.databind.node.ObjectNode)json.tree(KnowledgeFixtures.batch("fixture","approved","allowed").activities().get(0));
        ((com.fasterxml.jackson.databind.node.ArrayNode)tree.path("personIds")).set(0,com.fasterxml.jackson.databind.node.TextNode.valueOf(stable));
        var activity=json.read(json.write(tree),dev.parliament.tracking.Activity.class);
        tracking.importDraft(activity).block();tracking.publish(activity.id(),activity.version(),"fixture-reviewer","").block();
        fixtureUser();
        db.sql("INSERT INTO tracking_follow(user_id,target_kind,target_id) VALUES('fixture-user','person',:id)").bind("id",stable).fetch().rowsUpdated().block();
        var disabled=new KnowledgeIdentity(db,false);disabled.initialize();
        assertThat(disabled.enabled()).isFalse();assertThat(disabled.hasStorage()).isTrue();
        String rebuiltAlias="p_"+KnowledgeJson.hash("after-rebuild");
        assertThat(disabled.resolve(rebuiltAlias).block()).isEqualTo(stable);
        assertThat(db.sql("SELECT "+disabled.personSql()+" AS stable FROM parliament_person p WHERE identity_key='after-rebuild'").map((r,m)->r.get("stable",String.class)).one().block()).isEqualTo(stable);
        var tx=TransactionalOperator.create(new R2dbcTransactionManager(db.getConnectionFactory()));
        var events=new TrackingRepository(db,tx,mapper,disabled);var directory=new dev.parliament.tracking.TrackingDirectory(db,events,disabled);
        assertThat(directory.person(stable).block().id()).isEqualTo(stable);
        assertThat(directory.person(rebuiltAlias).block().id()).isEqualTo(stable);
        assertThat(directory.people(null).collectList().block()).extracting(dev.parliament.tracking.TrackingDirectory.Person::id).containsExactly(stable);
        assertThat(events.feed(rebuiltAlias,null,null,null,null,null,20).block().items()).extracting(dev.parliament.tracking.Activity::id).containsExactly(activity.id());
        var policy=new dev.parliament.tracking.TrackingAuthPolicy("http://localhost:3000");
        var auth=new dev.parliament.tracking.TrackingAuthRepository(db,events,mapper,policy,java.time.Clock.systemUTC(),new dev.parliament.tracking.TrackingIssues(),tx,disabled);
        assertThat(auth.follows("fixture-user").collectList().block()).extracting(dev.parliament.tracking.TrackingAuthRepository.Follow::targetId).containsExactly(stable);
        auth.replaceFollows("fixture-user",List.of(new dev.parliament.tracking.TrackingAuthRepository.Follow("person",stable)),"weekly").block();
        assertThat(auth.follows("fixture-user").collectList().block()).extracting(dev.parliament.tracking.TrackingAuthRepository.Follow::targetId).containsExactly(stable);
        assertThat(new dev.parliament.tracking.TrackingDigests(db,events,auth,policy,tx,disabled)
                .build("weekly",java.time.Instant.now().minusSeconds(60),java.time.Instant.now().plusSeconds(60)).block().queued()).isEqualTo(1);
    }
    @Test void disabledKnowledgeWithoutInstalledTablesPreservesLegacyQueries() throws Exception {
        try(var c=DriverManager.getConnection(mysql.jdbcUrl(),mysql.username(),mysql.password())) {
            for(String script:List.of("sql/migrations/015-knowledge-relations-down.sql","sql/migrations/014-knowledge-documents-down.sql","sql/migrations/013-knowledge-entities-down.sql"))
                ScriptUtils.executeSqlScript(c,new ClassPathResource(script));
        }
        db.sql("INSERT INTO parliament_person(identity_key,canonical_name,person_kind,resolution_status) VALUES('legacy-key','가상 의원','LEGISLATOR','RESOLVED')").fetch().rowsUpdated().block();
        var disabled=new KnowledgeIdentity(db,false);disabled.initialize();
        assertThat(disabled.hasStorage()).isFalse();assertThat(disabled.resolve("p_unmapped").block()).isEqualTo("p_unmapped");
        assertThatCode(()->disabled.refresh().block()).doesNotThrowAnyException();
        var mapper=new ObjectMapper().registerModule(new JavaTimeModule());var tx=TransactionalOperator.create(new R2dbcTransactionManager(db.getConnectionFactory()));
        var events=new TrackingRepository(db,tx,mapper,disabled);var directory=new dev.parliament.tracking.TrackingDirectory(db,events,disabled);
        String legacy="p_"+KnowledgeJson.hash("legacy-key");
        assertThat(directory.person(legacy).block().id()).isEqualTo(legacy);
        assertThat(directory.people(null).collectList().block()).extracting(dev.parliament.tracking.TrackingDirectory.Person::id).containsExactly(legacy);
        var auth=new dev.parliament.tracking.TrackingAuthRepository(db,events,mapper,new dev.parliament.tracking.TrackingAuthPolicy("http://localhost:3000"),java.time.Clock.systemUTC(),new dev.parliament.tracking.TrackingIssues(),tx,disabled);
        fixtureUser();auth.replaceFollows("fixture-user",List.of(new dev.parliament.tracking.TrackingAuthRepository.Follow("person",legacy)),"weekly").block();
        assertThat(auth.follows("fixture-user").collectList().block()).hasSize(1);
    }
    @Test void partialKnowledgeInstallationCannotSilentlyChangeStoredAddresses() throws Exception {
        db.sql("INSERT INTO parliament_person(identity_key,canonical_name,person_kind,resolution_status) VALUES('before-rebuild','가상 의원','LEGISLATOR','RESOLVED')").fetch().rowsUpdated().block();
        identities.initialize();String stable=identities.forIdentity("before-rebuild").block();
        identities.bind("after-rebuild",stable,"verified-rebuild").block();
        try(var c=DriverManager.getConnection(mysql.jdbcUrl(),mysql.username(),mysql.password())) {
            ScriptUtils.executeSqlScript(c,new ClassPathResource("sql/migrations/015-knowledge-relations-down.sql"));
        }
        var disabled=new KnowledgeIdentity(db,false);
        assertThatThrownBy(disabled::initialize).isInstanceOf(IllegalStateException.class).hasMessageContaining("incomplete knowledge schema");
        assertThat(db.sql("SELECT entity_id FROM knowledge_identity_binding WHERE identity_key='after-rebuild'").map((r,m)->r.get("entity_id",String.class)).one().block()).isEqualTo(stable);
    }
    @Test void rejectedLineageCorrectionHidesTheCurrentEdgeAndPreservesPriorContext() {
        var first=withLineage("batch_first","rel_lineage","approved");
        var old=repository.importBatch(first).block().batch();repository.review(first.id(),"publish","fixture-reviewer","원안 반영 검수").block();
        assertThat(reads.lineage("b_test").block().items()).hasSize(1);
        var correction=withLineage("batch_correction","rel_lineage","rejected");
        repository.importBatch(correction).block();repository.review(correction.id(),"publish","fixture-reviewer","원안 반영 연결 정정").block();
        assertThat(reads.lineage("b_test").block().items()).isEmpty();
        assertThat(reads.lineage("b_alternative").block().items()).isEmpty();
        assertThat(reads.context("a_test",null).block().relations()).noneMatch(r->r.type().equals("incorporated_into_alternative"));
        var prior=reads.context("a_test",old.activities().get(0).version()).block();
        assertThat(prior.relations()).anyMatch(r->r.type().equals("incorporated_into_alternative")&&r.decision().equals("approved"));
        assertThat(prior.evidence()).extracting(KnowledgeReads.PublicEvidence::id).contains("ev_test");
    }
    @Test void changingExtractionRelationIdsCannotDuplicateOrRestoreAnObsoleteLineageEdge() {
        var first=withLineage("batch_first","rel_original_extraction","approved");
        repository.importBatch(first).block();repository.review(first.id(),"publish","fixture-reviewer","검수").block();
        var json=new KnowledgeJson(new ObjectMapper().registerModule(new JavaTimeModule()));
        var next=json.read(json.write(withLineage("batch_next","rel_new_extraction","approved")).replace("extract_v1","extract_v2").replace("ev_test","ev_second_extraction"),KnowledgeBatch.class);
        repository.importBatch(next).block();repository.review(next.id(),"publish","fixture-reviewer","재추출 검수").block();
        assertThat(reads.lineage("b_test").block().items()).extracting(Relation::id).containsExactly("rel_new_extraction");
        var correction=withLineage("batch_correction","rel_newer_extraction","rejected");
        repository.importBatch(correction).block();repository.review(correction.id(),"publish","fixture-reviewer","연결 기각").block();
        assertThat(reads.lineage("b_test").block().items()).isEmpty();
    }
    private KnowledgeBatch withLineage(String batchId,String relationId,String decision) {
        var b=KnowledgeFixtures.batch(batchId,"approved","allowed");
        var relation=new Relation(relationId,"b_test","b_alternative","incorporated_into_alternative",List.of("ev_test"),decision,"합성 계보 검수");
        var c=b.contexts().get(0);
        return new KnowledgeBatch(b.id(),b.issueId(),List.of(b.entities().get(0),b.entities().get(1),new Entity("b_alternative","bill","합성 시험 대안",List.of(),List.of(),List.of())),
                b.documents(),b.evidence(),List.of(b.relations().get(0),relation),b.activities(),
                List.of(new Context(c.eventId(),c.eventVersion(),List.of("rel_test",relationId),c.evidenceIds(),c.documentIds(),c.changeKind())));
    }
    private void fixtureUser() {
        db.sql("INSERT INTO tracking_user(user_id,email,unsubscribe_hash,unsubscribe_token,email_enabled,verified_at) VALUES('fixture-user','fixture@example.test',:hash,:token,true,CURRENT_TIMESTAMP(6))")
                .bind("hash","b".repeat(64)).bind("token","c".repeat(43)).fetch().rowsUpdated().block();
    }
}
