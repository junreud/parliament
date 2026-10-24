package dev.parliament.knowledge;

import dev.parliament.tracking.Activity;
import java.time.Instant;
import java.util.List;
import static dev.parliament.knowledge.KnowledgeBatch.*;

final class KnowledgeFixtures {
    static final Instant TIME = Instant.parse("2024-07-12T01:00:00Z");
    static KnowledgeBatch batch(String id, String decision, String license) {
        var evidence = new Evidence("ev_test", "doc_test", "a".repeat(64), "extract_v1", "seg_test", 0, 5);
        var person = new Entity("p_test", "person", "가상 의원", List.of(new Identifier("FIXTURE_ID", "P1")),
                List.of(new Fact("성명", "가상 의원", List.of("ev_test"))), List.of());
        var bill = new Entity("b_test", "bill", "가상 시험 법안", List.of(), List.of(), List.of());
        var mention = new Mention("mention_test", "가상 의원", 0, 5, List.of("p_test"), "p_test", decision);
        var doc = new Document("doc_test", "a".repeat(64), "fixture", "row_test",
                "https://assembly.go.kr/test-fixture", "합성 표본", "pdf", "available", license,
                TIME, TIME, "raw/fixture/a.pdf", "extract_v1",
                List.of(new Segment("seg_test", "가상 의원 대표발의", "pdf:page=1", List.of(mention))),
                "observation_test", "second");
        var relation = new Relation("rel_test", "p_test", "b_test", "lead_sponsor",
                List.of("ev_test"), decision, "합성 검수 표본");
        var activity = new Activity("a_test", "bill", "가상 시험 법안 발의", null, "proposed",
                List.of("p_test"), List.of("child-support-advance"), "b_test", TIME, TIME, TIME,
                doc.sourceUrl(), List.of(new Activity.Evidence("ev_test", doc.sourceUrl(), null,
                "pdf:page=1", doc.version())), List.of(), "합성 테스트 데이터", false, "v_test");
        return new KnowledgeBatch(id, "child-support-advance", List.of(person, bill), List.of(doc),
                List.of(evidence), List.of(relation), List.of(activity),
                List.of(new Context(activity.id(), activity.version(), List.of(relation.id()),
                List.of(evidence.id()), List.of(doc.id()), "new_record")));
    }
    static KnowledgeBatch documents(KnowledgeBatch b, List<Document> docs) {
        return new KnowledgeBatch(b.id(), b.issueId(), b.entities(), docs, b.evidence(), b.relations(), b.activities(), b.contexts());
    }
    static KnowledgeBatch distinctEventAndDocument(KnowledgeBatch b,String batchId,String eventId,String documentId) {
        var d=b.documents().get(0);
        var doc=new Document(documentId,d.version(),d.sourceKey(),d.recordKey(),d.sourceUrl(),d.title(),d.format(),d.bodyStatus(),
                d.licenseStatus(),d.publishedAt(),d.collectedAt(),d.rawStorageKey(),d.extractionVersion(),d.segments(),"observation_"+documentId,d.datePrecision());
        var e=b.evidence().get(0);
        var evidence=new Evidence(e.id(),doc.id(),doc.version(),doc.extractionVersion(),e.segmentId(),e.start(),e.end());
        var a=b.activities().get(0);
        var activity=new Activity(eventId,a.type(),a.title(),a.summary(),a.stage(),a.personIds(),a.topics(),a.billId(),a.occurredAt(),a.publishedAt(),
                a.collectedAt(),a.sourceUrl(),a.evidence(),a.votes(),a.coverage(),a.corrected(),a.version());
        var c=b.contexts().get(0);
        return new KnowledgeBatch(batchId,b.issueId(),b.entities(),List.of(doc),List.of(evidence),b.relations(),List.of(activity),
                List.of(new Context(eventId,activity.version(),c.relationIds(),c.evidenceIds(),List.of(documentId),c.changeKind())));
    }
}
