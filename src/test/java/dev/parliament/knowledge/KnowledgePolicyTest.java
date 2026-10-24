package dev.parliament.knowledge;

import static org.assertj.core.api.Assertions.*;
import static dev.parliament.knowledge.KnowledgeBatch.*;
import java.util.List;
import org.junit.jupiter.api.Test;

class KnowledgePolicyTest {
    private final KnowledgePolicy policy = new KnowledgePolicy();
    @Test void validatesRealCoordinatesBeforeAcceptingEvidence() {
        var b = KnowledgeFixtures.batch("batch_test", "approved", "allowed");
        policy.validate(b);
        var bad = new Evidence("ev_test", "doc_test", "a".repeat(64), "extract_v1", "seg_test", 0, 500);
        assertThatThrownBy(() -> policy.validate(new KnowledgeBatch(b.id(), b.issueId(), b.entities(),
                b.documents(), List.of(bad), b.relations(), b.activities(), b.contexts())))
                .isInstanceOf(IllegalArgumentException.class).hasMessageContaining("range");
    }
    @Test void pendingActorsCannotBecomePublicActivityParticipants() {
        var b = KnowledgeFixtures.batch("batch_test", "pending", "allowed");
        policy.validate(b);
        assertThatThrownBy(() -> policy.validatePublication(b)).isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("participant");
    }
    @Test void restrictedEvidenceCannotPublishAFactEvenAfterReview() {
        var b = KnowledgeFixtures.batch("batch_test", "approved", "restricted");
        policy.validate(b);
        assertThatThrownBy(() -> policy.validatePublication(b)).isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("evidence");
    }
    @Test void mentionSurfaceMustMatchTheOriginalCodePointRange() {
        var b = KnowledgeFixtures.batch("batch_test", "approved", "allowed");
        var doc = b.documents().get(0);
        var seg = new Segment("seg_test", "가상 의원 대표발의", "pdf:page=1",
                List.of(new Mention("m_bad", "다른 인물", 0, 5, List.of("p_test"), "p_test", "approved")));
        var bad = new Document(doc.id(), doc.version(), doc.sourceKey(), doc.recordKey(), doc.sourceUrl(),
                doc.title(), doc.format(), doc.bodyStatus(), doc.licenseStatus(), doc.publishedAt(),
                doc.collectedAt(), doc.rawStorageKey(), doc.extractionVersion(), List.of(seg), doc.observationId(), doc.datePrecision());
        assertThatThrownBy(() -> policy.validate(KnowledgeFixtures.documents(b, List.of(bad))))
                .isInstanceOf(IllegalArgumentException.class).hasMessageContaining("surface");
    }
    @Test void unicodeOffsetsCountCodePointsAndPendingOverlapsRemainCandidates() {
        assertThat(KnowledgePolicy.slice("😀가상 의원",1,6)).isEqualTo("가상 의원");
        var b=KnowledgeFixtures.batch("batch_test","approved","allowed");var d=b.documents().get(0);
        var overlap=new Mention("m_candidate","의원",3,5,List.of("p_test"),null,"pending");
        var s=new Segment("seg_test","가상 의원 대표발의","pdf:page=1",List.of(d.segments().get(0).mentions().get(0),overlap));
        var changed=new Document(d.id(),d.version(),d.sourceKey(),d.recordKey(),d.sourceUrl(),d.title(),d.format(),d.bodyStatus(),d.licenseStatus(),d.publishedAt(),d.collectedAt(),d.rawStorageKey(),d.extractionVersion(),List.of(s),d.observationId(),d.datePrecision());
        var versioning=new KnowledgeVersioning(new com.fasterxml.jackson.databind.ObjectMapper().registerModule(new com.fasterxml.jackson.datatype.jsr310.JavaTimeModule()));
        assertThatCode(()->policy.validatePublication(versioning.prepare(KnowledgeFixtures.documents(b,List.of(changed))))).doesNotThrowAnyException();
        var approved=new Mention(overlap.id(),overlap.surface(),overlap.start(),overlap.end(),List.of("p_test"),"p_test","approved");
        var bad=new Document(d.id(),d.version(),d.sourceKey(),d.recordKey(),d.sourceUrl(),d.title(),d.format(),d.bodyStatus(),d.licenseStatus(),d.publishedAt(),d.collectedAt(),d.rawStorageKey(),d.extractionVersion(),
                List.of(new Segment(s.id(),s.text(),s.locator(),List.of(s.mentions().get(0),approved))),d.observationId(),d.datePrecision());
        assertThatThrownBy(()->policy.validatePublication(KnowledgeFixtures.documents(b,List.of(bad)))).hasMessageContaining("overlap");
    }
    @Test void oneBatchCannotAssignConflictingDecisionsToTheSameLineageEdge() {
        var b=KnowledgeFixtures.batch("batch_test","approved","allowed");
        var first=new Relation("edge_first","b_test","b_alternative","incorporated_into_alternative",List.of("ev_test"),"approved","합성 검수");
        var second=new Relation("edge_second","b_test","b_alternative","incorporated_into_alternative",List.of("ev_test"),"rejected","합성 정정");
        var duplicate=new KnowledgeBatch(b.id(),b.issueId(),List.of(b.entities().get(0),b.entities().get(1),new Entity("b_alternative","bill","합성 대안",List.of(),List.of(),List.of())),
                b.documents(),b.evidence(),List.of(first,second,b.relations().get(0)),b.activities(),b.contexts());
        assertThatThrownBy(()->policy.validate(duplicate)).hasMessageContaining("duplicate bill lineage");
    }
    @Test void organizationAndPolicyFactsNeedUsableEvidenceWithoutAnyActivity() {
        for(String kind:List.of("organization","policy")) {
            var b=KnowledgeFixtures.batch("unusable_fact","approved","unknown");
            var entity=new Entity("entity_test",kind,"합성 대상",List.of(),List.of(new Fact("소개","확인 필요",List.of("ev_test"))),List.of());
            var d=b.documents().get(0);
            var doc=new Document(d.id(),d.version(),d.sourceKey(),d.recordKey(),d.sourceUrl(),d.title(),d.format(),d.bodyStatus(),d.licenseStatus(),
                    d.publishedAt(),d.collectedAt(),d.rawStorageKey(),d.extractionVersion(),
                    List.of(new Segment("seg_test",d.segments().get(0).text(),"pdf:page=1",List.of())),d.observationId(),d.datePrecision());
            var onlyFact=new KnowledgeBatch(b.id(),b.issueId(),List.of(entity),List.of(doc),b.evidence(),List.of(),List.of(),List.of());
            assertThatThrownBy(()->policy.validatePublication(onlyFact)).hasMessageContaining("fact evidence");
        }
    }
    @Test void anApprovedNameInAnotherSourceSpanDoesNotApproveThePersonsNewClaim() {
        var b=KnowledgeFixtures.batch("unreviewed_span","approved","allowed");var d=b.documents().get(0);
        var candidate=new Mention("unreviewed_name","가상 의원",0,5,List.of("p_test"),null,"pending");
        var doc=new Document(d.id(),d.version(),d.sourceKey(),d.recordKey(),d.sourceUrl(),d.title(),d.format(),d.bodyStatus(),d.licenseStatus(),
                d.publishedAt(),d.collectedAt(),d.rawStorageKey(),d.extractionVersion(),
                List.of(d.segments().get(0),new Segment("new_span","가상 의원 시험 직위","pdf:page=2",List.of(candidate))),d.observationId(),d.datePrecision());
        var e=new Evidence("new_evidence",doc.id(),doc.version(),doc.extractionVersion(),"new_span",0,5);
        var person=new Entity("p_test","person","가상 의원",List.of(),List.of(new Fact("직위","시험 직위",List.of(e.id()))),List.of());
        var changed=new KnowledgeBatch(b.id(),b.issueId(),List.of(person),List.of(doc),List.of(b.evidence().get(0),e),List.of(),List.of(),List.of());
        assertThatThrownBy(()->policy.validatePublication(changed)).hasMessageContaining("identity");
    }
    @Test void identityEvidenceMustContainTheEntireApprovedName() {
        var b=KnowledgeFixtures.batch("clipped_identity","approved","allowed");var e=b.evidence().get(0);
        var clipped=new Evidence(e.id(),e.documentId(),e.documentVersion(),e.extractionVersion(),e.segmentId(),0,4);
        var person=b.entities().get(0);
        var changed=new KnowledgeBatch(b.id(),b.issueId(),List.of(new Entity(person.id(),person.kind(),person.name(),person.identifiers(),List.of(),List.of())),
                b.documents(),List.of(clipped),List.of(),List.of(),List.of());
        assertThatThrownBy(()->policy.validatePublication(changed)).hasMessageContaining("identity");
    }
}
