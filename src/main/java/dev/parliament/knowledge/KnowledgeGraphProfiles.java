package dev.parliament.knowledge;

import com.fasterxml.jackson.databind.ObjectMapper;
import java.time.Instant;
import java.util.*;
import org.springframework.r2dbc.core.DatabaseClient;
import reactor.core.publisher.Mono;
import static dev.parliament.knowledge.KnowledgeBatch.*;

/** Each source supplies a replacement snapshot; a roster cannot erase another source's biography. */
final class KnowledgeGraphProfiles {
    record Revision(KnowledgeBatch batch, Instant reviewedAt, int bytes) {
        Revision(KnowledgeBatch batch,Instant reviewedAt) {this(batch,reviewedAt,0);}
    }
    record FactClaim(Fact fact, Revision revision) {}
    record OfficeClaim(Tenure tenure, Revision revision, String organizationName) {}
    record Snapshot(List<FactClaim> facts, List<OfficeClaim> offices) {}
    private final DatabaseClient db;
    private final KnowledgeJson json;
    KnowledgeGraphProfiles(DatabaseClient db, ObjectMapper mapper) { this.db=db;this.json=new KnowledgeJson(mapper); }

    Mono<Snapshot> snapshot(String id) {
        var query=db.sql("""
                SELECT b.payload,b.reviewed_at FROM knowledge_entity_version ev
                JOIN knowledge_batch b ON b.batch_id=ev.batch_id
                WHERE ev.entity_id=:id AND b.review_state='published'
                ORDER BY b.reviewed_at DESC,b.batch_id DESC LIMIT :budget
                """).bind("id",id).bind("budget",KnowledgeGraphLimits.REVISIONS+1);
        return KnowledgeGraphLimits.timed(Mono.defer(()->{
            long deadline=KnowledgeGraphLimits.deadline();
            return KnowledgeGraphLimits.read(query,json).map(revisions->merge(id,revisions,deadline));
        }));
    }

    static Snapshot merge(String id, List<Revision> revisions) {
        return merge(id,revisions,KnowledgeGraphLimits.deadline());
    }
    static Snapshot merge(String id, List<Revision> revisions,long deadline) {
        Set<String> superseded=new HashSet<>();
        List<FactClaim> facts=new ArrayList<>();List<OfficeClaim> offices=new ArrayList<>();
        for(Revision revision:ordered(revisions)) {
            KnowledgeGraphLimits.checkTime(deadline);
            KnowledgeBatch b=revision.batch();
            Entity e=b.entities().stream().filter(x->x.id().equals(id)).findFirst().orElse(null);
            if(e==null)continue;
            Set<String> sourceScopes=new HashSet<>();
            e.facts().forEach(f->sourceScopes.addAll(scopes(b,f.evidenceIds())));
            e.tenures().forEach(t->sourceScopes.addAll(scopes(b,t.evidenceIds())));
            // Empty person snapshots can withdraw only sources with usable, approved identity evidence.
            if(e.facts().isEmpty()&&e.tenures().isEmpty())b.documents().stream()
                    .filter(d->!e.kind().equals("person")||KnowledgePolicy.reviewedPersonDocument(b,id,d))
                    .forEach(d->sourceScopes.add(scope(d)));
            for(Fact f:e.facts())if(usable(b,f.evidenceIds())&&!scopes(b,f.evidenceIds()).stream().anyMatch(superseded::contains))
                facts.add(new FactClaim(f,revision));
            for(Tenure t:e.tenures())if(usable(b,t.evidenceIds())&&!scopes(b,t.evidenceIds()).stream().anyMatch(superseded::contains)) {
                String name=b.entities().stream().filter(x->x.id().equals(t.organizationId())).map(Entity::name).findFirst().orElse(t.organizationId());
                offices.add(new OfficeClaim(t,revision,name));
            }
            superseded.addAll(sourceScopes);
        }
        return new Snapshot(List.copyOf(facts),List.copyOf(offices));
    }
    static List<Revision> ordered(List<Revision> revisions) {
        return revisions.stream().sorted(Comparator.comparing(Revision::reviewedAt,Comparator.nullsLast(Comparator.reverseOrder()))
                .thenComparing(r->r.batch().id(),Comparator.reverseOrder())).toList();
    }
    static boolean usable(KnowledgeBatch b,List<String> evidenceIds) {
        return evidenceIds!=null&&!evidenceIds.isEmpty()&&evidenceIds.stream().allMatch(id->
                b.evidence().stream().anyMatch(e->e.id().equals(id)&&KnowledgePolicy.usable(b,e)));
    }
    static boolean confirmedCurrentSource(OfficeClaim office,List<FactClaim> facts) {
        Set<String> officeScopes=scopes(office.revision().batch(),office.tenure().evidenceIds());
        List<FactClaim> markers=facts.stream().filter(f->f.fact().label().equals("명부 현재성")
                &&scopes(f.revision().batch(),f.fact().evidenceIds()).stream().anyMatch(officeScopes::contains)).toList();
        // Older reviewed wiki snapshots have no marker; explicit unknown/dated markers are conservative.
        return markers.isEmpty()||markers.stream().allMatch(f->Set.of("source_current_roster","source_profile","source_rendered_profile").contains(f.fact().value()));
    }
    private static Set<String> scopes(KnowledgeBatch b,List<String> evidenceIds) {
        Set<String> scopes=new HashSet<>();
        for(Evidence e:b.evidence())if(evidenceIds.contains(e.id()))b.documents().stream()
                .filter(d->d.id().equals(e.documentId())&&d.version().equals(e.documentVersion())&&d.extractionVersion().equals(e.extractionVersion()))
                .forEach(d->scopes.add(scope(d)));
        return scopes;
    }
    private static String scope(Document d) { return d.sourceKey()+"\u0000"+d.recordKey(); }
}
