package dev.parliament.knowledge;

import com.fasterxml.jackson.databind.ObjectMapper;
import dev.parliament.tracking.TrackingRepository;
import org.springframework.http.HttpStatus;
import org.springframework.r2dbc.core.DatabaseClient;
import org.springframework.transaction.reactive.TransactionalOperator;
import org.springframework.web.server.ResponseStatusException;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;
import java.time.Instant;

/** Candidate import never implies publication; review is atomic with existing event review. */
public final class KnowledgeRepository {
    public record ImportResult(String id,String state,boolean replayed,KnowledgeBatch batch) {}
    public record Saved(KnowledgeBatch batch,String state,String reviewer,String reason,Instant reviewedAt) {}
    private final DatabaseClient db;
    private final TransactionalOperator tx;
    private final TrackingRepository tracking;
    private final KnowledgeIdentity identities;
    private final KnowledgeJson json;
    private final KnowledgeVersioning versions;
    private final KnowledgeStore store;
    private final KnowledgePolicy policy=new KnowledgePolicy();
    public KnowledgeRepository(DatabaseClient db,TransactionalOperator tx,ObjectMapper mapper,TrackingRepository tracking,KnowledgeIdentity identities) {
        this.db=db;this.tx=tx;this.tracking=tracking;this.identities=identities;json=new KnowledgeJson(mapper);
        versions=new KnowledgeVersioning(mapper);store=new KnowledgeStore(db,json);
    }
    public Mono<ImportResult> importBatch(KnowledgeBatch input) {
        policy.validate(input);
        KnowledgeBatch batch=versions.prepare(input);
        String hash=KnowledgeJson.hash(versions.content(batch));
        Mono<ImportResult> work=db.sql("INSERT IGNORE INTO knowledge_batch(batch_id,issue_id,payload_hash,payload) VALUES(:id,:issue,:hash,:payload)")
            .bind("id",batch.id()).bind("issue",batch.issueId()).bind("hash",hash).bind("payload",json.write(batch)).fetch().rowsUpdated()
            .flatMap(inserted->db.sql("SELECT payload_hash,review_state,payload FROM knowledge_batch WHERE batch_id=:id FOR UPDATE")
                .bind("id",batch.id()).fetch().one().flatMap(row->{
                    if(!hash.equals(row.get("payload_hash")))return Mono.error(KnowledgeIdentity.conflict("immutable batch conflict"));
                    KnowledgeBatch saved=json.read((String)row.get("payload"),KnowledgeBatch.class);
                    return store.documents(input).then(inserted==0?Mono.just(new ImportResult(batch.id(),(String)row.get("review_state"),true,saved)):
                        Flux.fromIterable(batch.activities()).concatMap(tracking::importDraft).then(store.indices(batch))
                            .thenReturn(new ImportResult(batch.id(),"draft",false,batch)));
                }));
        return tx.transactional(work);
    }
    public Mono<Saved> get(String id) {
        dev.parliament.tracking.TrackingPolicy.id(id);
        return db.sql("SELECT payload,review_state,reviewer,review_reason,reviewed_at FROM knowledge_batch WHERE batch_id=:id").bind("id",id)
            .map((r,m)->new Saved(json.read(r.get("payload",String.class),KnowledgeBatch.class),r.get("review_state",String.class),r.get("reviewer",String.class),r.get("review_reason",String.class),r.get("reviewed_at",Instant.class)))
            .one().switchIfEmpty(Mono.error(notFound()));
    }
    public Mono<Saved> review(String id,String decision,String reviewer,String reason) {
        KnowledgePolicy.require(decision!=null&&java.util.Set.of("publish","reject").contains(decision),"unsupported review decision");
        KnowledgePolicy.require(reviewer!=null&&!reviewer.isBlank()&&reviewer.length()<=100,"reviewer required");
        KnowledgePolicy.require(reason!=null&&!reason.isBlank()&&reason.length()<=1000,"review reason required");
        Mono<Saved> work=db.sql("SELECT review_state FROM knowledge_batch WHERE batch_id=:id FOR UPDATE").bind("id",id).fetch().one()
            .switchIfEmpty(Mono.error(notFound())).flatMap(row->get(id)).flatMap(saved->{
                String wanted=decision.equals("publish")?"published":"rejected";
                if(saved.state().equals(wanted))return Mono.just(saved);
                if(!saved.state().equals("draft"))return Mono.error(KnowledgeIdentity.conflict("review decision is immutable"));
                var b=saved.batch();
                Mono<Void> action;
                if(decision.equals("publish")) {
                    action=identities.verifiedExistingPeople(b).flatMap(verified->{
                        policy.validatePublication(b,verified);
                        return Flux.fromIterable(b.activities()).concatMap(a->tracking.publishFromKnowledge(a.id(),a.version(),reviewer,reason,b.id())).then()
                            .thenMany(Flux.fromIterable(b.entities()).concatMap(e->identities.register(e,b.id()))).then();
                    });
                } else action=Flux.fromIterable(b.activities()).concatMap(a->tracking.rejectFromKnowledge(a.id(),a.version(),b.id())).then();
                return action.then(db.sql("UPDATE knowledge_batch SET review_state=:state,reviewer=:reviewer,review_reason=:reason,reviewed_at=:at WHERE batch_id=:id AND review_state='draft'")
                    .bind("state",wanted).bind("reviewer",reviewer).bind("reason",reason).bind("at",Instant.now()).bind("id",id).fetch().rowsUpdated()).then(get(id));
            });
        return tx.transactional(work);
    }
    static ResponseStatusException notFound() { return new ResponseStatusException(HttpStatus.NOT_FOUND,"published knowledge record unavailable"); }
}
