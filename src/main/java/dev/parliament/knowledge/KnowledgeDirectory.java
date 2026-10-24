package dev.parliament.knowledge;

import dev.parliament.tracking.TrackingDirectory;
import dev.parliament.tracking.TrackingRepository;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import org.springframework.r2dbc.core.DatabaseClient;
import reactor.core.publisher.Mono;
import reactor.core.publisher.Flux;
import java.util.List;

/** Adapts approved canonical entities to the existing v1 directory wire. */
public final class KnowledgeDirectory {
    private final DatabaseClient db;
    private final TrackingRepository events;
    private final KnowledgeIdentity ids;
    private final KnowledgeJson json=new KnowledgeJson(new ObjectMapper().registerModule(new JavaTimeModule()));
    public KnowledgeDirectory(DatabaseClient db,TrackingRepository events,KnowledgeIdentity ids) {this.db=db;this.events=events;this.ids=ids;}
    public Flux<TrackingDirectory.Person> people(String query) {
        return db.sql("SELECT entity_id,canonical_name FROM knowledge_entity WHERE entity_kind='person' AND published=true AND canonical_name LIKE :pattern ORDER BY canonical_name,entity_id LIMIT 100")
            .bind("pattern",pattern(query)).map((r,m)->new TrackingDirectory.Person(r.get("entity_id",String.class),r.get("canonical_name",String.class),"person",null,null,List.of())).all();
    }
    public Mono<TrackingDirectory.Person> person(String id) {
        return ids.resolve(id).flatMap(canonical->db.sql("SELECT canonical_name FROM knowledge_entity WHERE entity_id=:id AND entity_kind='person' AND published=true")
            .bind("id",canonical).map((r,m)->r.get("canonical_name",String.class)).one().switchIfEmpty(Mono.error(KnowledgeRepository.notFound()))
            .flatMap(name->events.feed(canonical,null,null,null,null,null,100).map(page->new TrackingDirectory.Person(canonical,name,"person",null,null,page.items()))));
    }
    public Flux<TrackingDirectory.Bill> bills(String query) {
        return db.sql("SELECT entity_id,canonical_name FROM knowledge_entity WHERE entity_kind='bill' AND published=true AND canonical_name LIKE :pattern ORDER BY canonical_name,entity_id LIMIT 100")
            .bind("pattern",pattern(query)).map((r,m)->new TrackingDirectory.Bill(r.get("entity_id",String.class),r.get("canonical_name",String.class),"unknown",List.of(),List.of(),null)).all();
    }
    public Mono<TrackingDirectory.Bill> bill(String id) {
        return db.sql("SELECT canonical_name FROM knowledge_entity WHERE entity_id=:id AND entity_kind='bill' AND published=true")
            .bind("id",id).map((r,m)->r.get("canonical_name",String.class)).one().switchIfEmpty(Mono.error(KnowledgeRepository.notFound()))
            .flatMap(name->db.sql("SELECT b.payload FROM knowledge_entity_version ev JOIN knowledge_batch b ON b.batch_id=ev.batch_id WHERE ev.entity_id=:id AND b.review_state='published' ORDER BY b.reviewed_at DESC LIMIT 1")
                .bind("id",id).map((r,m)->json.read(r.get("payload",String.class),KnowledgeBatch.class)).one()
                .map(b->{String url=sourceForBill(b,id);return new TrackingDirectory.Bill(id,name,"unknown",List.of(),List.of(),url);})
                .defaultIfEmpty(new TrackingDirectory.Bill(id,name,"unknown",List.of(),List.of(),null)));
    }
    private String sourceForBill(KnowledgeBatch b,String id) {
        var evidenceIds=java.util.stream.Stream.concat(
                b.entities().stream().filter(e->e.id().equals(id)).flatMap(e->e.facts().stream()).flatMap(f->f.evidenceIds().stream()),
                b.relations().stream().filter(r->r.decision().equals("approved")&&(r.subjectId().equals(id)||r.objectId().equals(id)))
                        .flatMap(r->r.evidenceIds().stream())).collect(java.util.stream.Collectors.toSet());
        return b.evidence().stream().filter(e->evidenceIds.contains(e.id())&&KnowledgePolicy.usable(b,e))
                .flatMap(e->b.documents().stream().filter(d->d.id().equals(e.documentId())&&d.version().equals(e.documentVersion())&&d.extractionVersion().equals(e.extractionVersion())))
                .map(KnowledgeBatch.Document::sourceUrl).findFirst().orElse(null);
    }
    private String pattern(String query) {return query==null?"%":"%"+query.replace("\\","\\\\").replace("%","\\%").replace("_","\\_")+"%";}
}
