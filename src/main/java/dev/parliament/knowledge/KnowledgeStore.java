package dev.parliament.knowledge;

import org.springframework.r2dbc.core.DatabaseClient;
import reactor.core.publisher.Mono;
import reactor.core.publisher.Flux;
import java.util.*;
import static dev.parliament.knowledge.KnowledgeBatch.*;

/** Normalized, queryable indices supplement the immutable batch snapshot. */
final class KnowledgeStore {
    private final DatabaseClient db;
    private final KnowledgeJson json;
    KnowledgeStore(DatabaseClient db,KnowledgeJson json) { this.db=db;this.json=json; }
    Mono<Void> documents(KnowledgeBatch b) { return Flux.fromIterable(b.documents()).concatMap(this::document).then(); }
    private Mono<Void> document(Document d) {
        String physical=json.write(List.of(d.id(),d.version(),d.sourceKey(),d.recordKey(),d.sourceUrl(),d.format()));
        String hash=KnowledgeJson.hash(physical);
        String extractHash=KnowledgeJson.hash(json.canonical(Map.of("title",d.title(),"bodyStatus",d.bodyStatus(),
                "licenseStatus",d.licenseStatus(),"publishedAt",d.publishedAt()==null?"unknown":d.publishedAt(),
                "datePrecision",d.datePrecision()==null?"unknown":d.datePrecision(),"segments",d.segments()),
                Set.of("decision","personId","candidatePersonIds")));
        String observationHash=KnowledgeJson.hash(json.write(Arrays.asList(d.id(),d.version(),d.observationId(),d.observedAt()==null?d.collectedAt():d.observedAt(),d.transitionId())));
        return db.sql("INSERT IGNORE INTO knowledge_document_version(document_id,version_id,content_hash,metadata,first_collected_at) VALUES(:id,:version,:hash,:payload,:at)")
            .bind("id",d.id()).bind("version",d.version()).bind("hash",hash).bind("payload",json.write(d)).bind("at",d.collectedAt()).fetch().rowsUpdated()
            .then(check("SELECT content_hash FROM knowledge_document_version WHERE document_id=:id AND version_id=:version FOR UPDATE",d.id(),d.version(),hash))
            .then(db.sql("INSERT IGNORE INTO knowledge_extraction(document_id,version_id,extraction_version,content_hash,segments) VALUES(:id,:version,:extract,:hash,:segments)")
                .bind("id",d.id()).bind("version",d.version()).bind("extract",d.extractionVersion()).bind("hash",extractHash).bind("segments",json.write(d.segments())).fetch().rowsUpdated())
            .then(db.sql("SELECT content_hash FROM knowledge_extraction WHERE document_id=:id AND version_id=:version AND extraction_version=:extract FOR UPDATE")
                .bind("id",d.id()).bind("version",d.version()).bind("extract",d.extractionVersion()).map((r,m)->r.get("content_hash",String.class)).one()
                .flatMap(existing->equal(existing,extractHash,"immutable extraction conflict")))
            .then(observation(d,observationHash));
    }
    private Mono<Void> observation(Document d,String hash) {
        var q=db.sql("INSERT IGNORE INTO knowledge_document_observation(observation_id,document_id,version_id,observed_at,transition_id,content_hash) VALUES(:observation,:id,:version,:at,:transition,:hash)")
            .bind("observation",d.observationId()).bind("id",d.id()).bind("version",d.version()).bind("at",d.observedAt()==null?d.collectedAt():d.observedAt()).bind("hash",hash);
        q=d.transitionId()==null?q.bindNull("transition",String.class):q.bind("transition",d.transitionId());
        return q.fetch().rowsUpdated().then(db.sql("SELECT content_hash FROM knowledge_document_observation WHERE observation_id=:id FOR UPDATE")
            .bind("id",d.observationId()).map((r,m)->r.get("content_hash",String.class)).one()
            .flatMap(old->equal(old,hash,"observation identity conflict")));
    }
    private Mono<Void> check(String sql,String id,String version,String hash) {
        return db.sql(sql).bind("id",id).bind("version",version).map((r,m)->r.get("content_hash",String.class)).one().flatMap(old->equal(old,hash,"immutable document conflict"));
    }
    private Mono<Void> equal(String old,String current,String reason) { return old.equals(current)?Mono.empty():Mono.error(KnowledgeIdentity.conflict(reason)); }
    Mono<Void> indices(KnowledgeBatch b) {
        return Flux.fromIterable(b.entities()).concatMap(e->db.sql("INSERT INTO knowledge_entity_version(batch_id,entity_id,payload) VALUES(:batch,:id,:payload)")
                .bind("batch",b.id()).bind("id",e.id()).bind("payload",json.write(e)).fetch().rowsUpdated()).then()
            .thenMany(Flux.fromIterable(b.evidence()).concatMap(e->db.sql("INSERT IGNORE INTO knowledge_evidence_registry(evidence_id,content_hash,payload) VALUES(:id,:hash,:payload)")
                .bind("id",e.id()).bind("hash",KnowledgeJson.hash(json.canonical(e,Set.of()))).bind("payload",json.write(e)).fetch().rowsUpdated()
                .then(db.sql("SELECT content_hash FROM knowledge_evidence_registry WHERE evidence_id=:id FOR UPDATE")
                    .bind("id",e.id()).map((r,m)->r.get("content_hash",String.class)).one())
                .flatMap(old->equal(old,KnowledgeJson.hash(json.canonical(e,Set.of())),"evidence ID must identify an immutable span"))
                .then(db.sql("INSERT INTO knowledge_evidence(batch_id,evidence_id,payload) VALUES(:batch,:id,:payload)")
                    .bind("batch",b.id()).bind("id",e.id()).bind("payload",json.write(e)).fetch().rowsUpdated()).then())).then()
            .thenMany(Flux.fromIterable(b.relations()).concatMap(r->db.sql("INSERT INTO knowledge_relation(batch_id,relation_id,subject_id,object_id,relation_type,decision,payload) VALUES(:batch,:id,:subject,:object,:type,:decision,:payload)")
                .bind("batch",b.id()).bind("id",r.id()).bind("subject",r.subjectId()).bind("object",r.objectId()).bind("type",r.type()).bind("decision",r.decision()).bind("payload",json.write(r)).fetch().rowsUpdated())).then()
            .thenMany(Flux.fromIterable(b.contexts()).concatMap(c->context(b,c))).then();
    }
    private Mono<Void> context(KnowledgeBatch b,Context c) {
        var a=b.activities().stream().filter(x->x.id().equals(c.eventId())&&x.version().equals(c.eventVersion())).findFirst().orElseThrow();
        String hash=KnowledgeJson.hash(json.canonical(c,Set.of()));
        return db.sql("INSERT IGNORE INTO knowledge_context(event_id,event_version,batch_id,issue_id,content_hash,change_kind,sort_at,date_kind,payload) VALUES(:id,:version,:batch,:issue,:hash,:kind,:at,:date,:payload)")
            .bind("id",c.eventId()).bind("version",c.eventVersion()).bind("batch",b.id()).bind("issue",b.issueId()).bind("hash",hash)
            .bind("kind",c.changeKind()).bind("at",a.occurredAt()==null?a.publishedAt():a.occurredAt()).bind("date",a.occurredAt()==null?"published":"occurred").bind("payload",json.write(c)).fetch().rowsUpdated()
            .then(db.sql("SELECT content_hash FROM knowledge_context WHERE event_id=:id AND event_version=:version FOR UPDATE")
                .bind("id",c.eventId()).bind("version",c.eventVersion()).map((r,m)->r.get("content_hash",String.class)).one()
                .flatMap(old->equal(old,hash,"immutable event context conflict; create a new activity version")));
    }
}
