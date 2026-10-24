package dev.parliament.knowledge;

import java.util.*;
import org.springframework.r2dbc.core.DatabaseClient;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;
import static dev.parliament.knowledge.KnowledgeGraphProfiles.Revision;

/** Complete the source snapshots and decision pairs before evaluating any graph neighborhood. */
final class KnowledgeGraphClosure {
    private record Pair(String subject,String object,String type) {}
    private static final int CHUNK=100;
    private static final int KEYS=10000;
    private final DatabaseClient db;
    private final KnowledgeJson json;
    KnowledgeGraphClosure(DatabaseClient db,KnowledgeJson json) {this.db=db;this.json=json;}

    Mono<Void> complete(Map<String,Revision> known,long deadline) {
        return complete(known,new HashSet<>(),new HashSet<>(),deadline);
    }
    private Mono<Void> complete(Map<String,Revision> known,Set<String> readEntities,Set<Pair> readPairs,long deadline) {
        return Mono.defer(()->{
            KnowledgeGraphLimits.checkTime(deadline);check(known);
            Set<String> entities=new TreeSet<>();Set<Pair> pairs=new LinkedHashSet<>();
            for(Revision revision:known.values()) {
                revision.batch().entities().forEach(e->entities.add(e.id()));
                revision.batch().relations().forEach(r->pairs.add(new Pair(r.subjectId(),r.objectId(),r.type())));
            }
            if(entities.size()>KEYS||pairs.size()>KEYS)return Mono.error(KnowledgeGraphLimits.exceeded());
            List<String> unreadEntities=entities.stream().filter(id->!readEntities.contains(id)).toList();
            List<Pair> unreadPairs=pairs.stream().filter(pair->!readPairs.contains(pair)).toList();
            if(unreadEntities.isEmpty()&&unreadPairs.isEmpty())return Mono.empty();
            readEntities.addAll(unreadEntities);readPairs.addAll(unreadPairs);
            return Flux.fromIterable(chunks(unreadEntities)).concatMap(this::entities)
                    .doOnNext(rows->add(known,rows,deadline)).thenMany(Flux.fromIterable(chunks(unreadPairs)).concatMap(this::pairs))
                    .doOnNext(rows->add(known,rows,deadline)).then(complete(known,readEntities,readPairs,deadline));
        });
    }
    private Mono<List<Revision>> entities(List<String> ids) {
        var query=db.sql("""
                SELECT b.payload,b.reviewed_at FROM knowledge_batch b WHERE b.review_state='published'
                  AND EXISTS(SELECT 1 FROM knowledge_entity_version ev WHERE ev.batch_id=b.batch_id AND ev.entity_id IN (:ids))
                ORDER BY b.reviewed_at DESC,b.batch_id DESC LIMIT :budget
                """).bind("ids",ids).bind("budget",KnowledgeGraphLimits.REVISIONS+1);
        return KnowledgeGraphLimits.read(query,json);
    }
    private Mono<List<Revision>> pairs(List<Pair> pairs) {
        StringJoiner predicates=new StringJoiner(" OR ");
        for(int i=0;i<pairs.size();i++)predicates.add("(r.subject_id=:subject"+i+" AND r.object_id=:object"+i+" AND r.relation_type=:type"+i+")");
        var query=db.sql("SELECT b.payload,b.reviewed_at FROM knowledge_batch b WHERE b.review_state='published'"
                +" AND EXISTS(SELECT 1 FROM knowledge_relation r WHERE r.batch_id=b.batch_id AND ("+predicates+"))"
                +" ORDER BY b.reviewed_at DESC,b.batch_id DESC LIMIT :budget").bind("budget",KnowledgeGraphLimits.REVISIONS+1);
        for(int i=0;i<pairs.size();i++)query=query.bind("subject"+i,pairs.get(i).subject()).bind("object"+i,pairs.get(i).object()).bind("type"+i,pairs.get(i).type());
        return KnowledgeGraphLimits.read(query,json);
    }
    private static <T> List<List<T>> chunks(List<T> values) {
        List<List<T>> chunks=new ArrayList<>();
        for(int start=0;start<values.size();start+=CHUNK)chunks.add(values.subList(start,Math.min(start+CHUNK,values.size())));
        return chunks;
    }
    private void add(Map<String,Revision> known,List<Revision> rows,long deadline) {
        KnowledgeGraphLimits.checkTime(deadline);
        rows.forEach(r->known.put(r.batch().id(),r));check(known);
    }
    private void check(Map<String,Revision> known) {
        if(known.size()>KnowledgeGraphLimits.REVISIONS||known.values().stream().mapToLong(Revision::bytes).sum()>KnowledgeGraphLimits.BYTES)
            throw KnowledgeGraphLimits.exceeded();
    }
}
