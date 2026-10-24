package dev.parliament.knowledge;

import org.springframework.r2dbc.core.DatabaseClient;
import org.springframework.web.server.ResponseStatusException;
import org.springframework.http.HttpStatus;
import reactor.core.publisher.Mono;
import reactor.core.publisher.Flux;
import dev.parliament.tracking.TrackingPolicy;

/** Durable public IDs are independent of staging keys. Exact aliases need explicit provenance. */
public final class KnowledgeIdentity {
    private final DatabaseClient db;
    private final boolean enabled;
    private boolean storageAvailable;
    public KnowledgeIdentity(DatabaseClient db,boolean enabled) { this.db=db;this.enabled=enabled;this.storageAvailable=enabled; }
    public boolean enabled() { return enabled; }
    public boolean hasStorage() { return storageAvailable; }
    public void initialize() {
        Long installed=db.sql("""
                SELECT COUNT(*) AS n FROM information_schema.tables WHERE table_schema=DATABASE()
                  AND table_name IN ('knowledge_entity','knowledge_identity_binding','knowledge_public_alias',
                    'knowledge_identifier','knowledge_batch','knowledge_entity_version','knowledge_document_version',
                    'knowledge_document_observation','knowledge_extraction','knowledge_evidence',
                    'knowledge_evidence_registry','knowledge_relation','knowledge_context')
                """).map((r,m)->r.get("n",Long.class)).one().block();
        if(installed==null||(installed!=0&&installed!=13)||enabled&&installed==0)
            throw new IllegalStateException("incomplete knowledge schema; apply migrations 013-015 and retain ID tables when disabling knowledge");
        storageAvailable=installed==13;
        if(storageAvailable)bootstrap().block();
    }
    public Mono<Void> bootstrap() {
        return db.sql("""
          SELECT i.identity_key FROM parliament_person_identifier i JOIN knowledge_identifier k
            ON k.namespace=i.identifier_namespace AND k.external_id=i.external_id
          GROUP BY i.identity_key HAVING COUNT(DISTINCT k.entity_id)>1 LIMIT 1
          """).fetch().one().flatMap(row->Mono.<Void>error(conflict("conflicting stable identities")))
            .then(db.sql("""
              INSERT IGNORE INTO knowledge_entity(entity_id,entity_kind,canonical_name,published)
              SELECT CONCAT('p_',SHA2(p.identity_key,256)),'person',p.canonical_name,true
              FROM parliament_person p LEFT JOIN knowledge_identity_binding b ON b.identity_key=p.identity_key
              WHERE b.identity_key IS NULL AND NOT EXISTS(SELECT 1 FROM parliament_person_identifier i
                JOIN knowledge_identifier k ON k.namespace=i.identifier_namespace AND k.external_id=i.external_id WHERE i.identity_key=p.identity_key)
              """).fetch().rowsUpdated())
            .then(db.sql("""
              INSERT IGNORE INTO knowledge_identity_binding(identity_key,entity_id)
              SELECT p.identity_key,COALESCE((SELECT k.entity_id FROM parliament_person_identifier i JOIN knowledge_identifier k
                ON k.namespace=i.identifier_namespace AND k.external_id=i.external_id WHERE i.identity_key=p.identity_key LIMIT 1),CONCAT('p_',SHA2(p.identity_key,256)))
              FROM parliament_person p
              """).fetch().rowsUpdated())
            .then(db.sql("""
              INSERT IGNORE INTO knowledge_public_alias(alias_id,entity_id)
              SELECT CONCAT('p_',SHA2(identity_key,256)),entity_id FROM knowledge_identity_binding
              """).fetch().rowsUpdated())
            .then(db.sql("""
              INSERT IGNORE INTO knowledge_identifier(namespace,external_id,entity_id)
              SELECT i.identifier_namespace,i.external_id,b.entity_id FROM parliament_person_identifier i JOIN knowledge_identity_binding b ON b.identity_key=i.identity_key
              """).fetch().rowsUpdated())
            .then(db.sql("""
              INSERT IGNORE INTO knowledge_entity(entity_id,entity_kind,canonical_name,published)
              SELECT v.bill_id,'bill',v.title,true FROM tracking_event e JOIN tracking_event_version v
                ON v.event_id=e.event_id AND v.version_id=e.latest_version
              WHERE v.review_state='published' AND v.bill_id IS NOT NULL
                AND (NOT EXISTS(SELECT 1 FROM knowledge_context c WHERE c.event_id=v.event_id AND c.event_version=v.version_id)
                  OR EXISTS(SELECT 1 FROM knowledge_context c JOIN knowledge_batch b ON b.batch_id=c.batch_id
                    WHERE c.event_id=v.event_id AND c.event_version=v.version_id AND b.review_state='published'))
              ORDER BY v.reviewed_at DESC,v.event_id DESC
              """).fetch().rowsUpdated()).then();
    }
    /** Persist IDs for staging rows collected after startup, before exposing them. */
    public Mono<Void> refresh() { return storageAvailable?bootstrap():Mono.empty(); }
    public String personSql() {
        return storageAvailable?"COALESCE((SELECT kb.entity_id FROM knowledge_identity_binding kb WHERE kb.identity_key=p.identity_key),CONCAT('p_',SHA2(p.identity_key,256)))":"CONCAT('p_',SHA2(p.identity_key,256))";
    }
    public String matches(String column,String parameter) {
        if(!storageAvailable)return column+"="+parameter;
        return "COALESCE((SELECT ka.entity_id FROM knowledge_public_alias ka WHERE ka.alias_id="+column+"),"+column+")=COALESCE((SELECT ki.entity_id FROM knowledge_public_alias ki WHERE ki.alias_id="+parameter+"),"+parameter+")";
    }
    public Mono<String> forIdentity(String key) {
        if(!storageAvailable)return Mono.just("p_"+KnowledgeJson.hash(key));
        return db.sql("SELECT entity_id FROM knowledge_identity_binding WHERE identity_key=:key").bind("key",key).map((r,m)->r.get("entity_id",String.class)).one();
    }
    public Mono<String> resolve(String id) {
        TrackingPolicy.id(id);
        if(!storageAvailable)return Mono.just(id);
        return db.sql("SELECT entity_id FROM knowledge_public_alias WHERE alias_id=:id").bind("id",id).map((r,m)->r.get("entity_id",String.class)).one().defaultIfEmpty(id);
    }
    public Mono<Void> bind(String key,String person,String batch) {
        TrackingPolicy.id(person);
        return db.sql("INSERT IGNORE INTO knowledge_identity_binding(identity_key,entity_id,evidence_batch_id) VALUES(:key,:person,:batch)")
            .bind("key",key).bind("person",person).bind("batch",batch).fetch().rowsUpdated()
            .then(forIdentity(key)).filter(person::equals).switchIfEmpty(Mono.error(conflict("stable identity binding conflict"))).then()
            .then(alias("p_"+KnowledgeJson.hash(key),person));
    }
    public Mono<Void> alias(String alias,String person) {
        return db.sql("INSERT IGNORE INTO knowledge_public_alias(alias_id,entity_id) VALUES(:alias,:person)")
            .bind("alias",alias).bind("person",person).fetch().rowsUpdated()
            .then(resolve(alias)).filter(person::equals).switchIfEmpty(Mono.error(conflict("public ID alias conflict"))).then();
    }
    /** Only unchanged, already-public identities may use the legacy empty-entity contract. */
    Mono<java.util.Set<String>> verifiedExistingPeople(KnowledgeBatch batch) {
        return Flux.fromIterable(batch.entities()).filter(e->e.kind().equals("person")).concatMap(entity->
            db.sql("SELECT entity_kind,canonical_name FROM knowledge_entity WHERE entity_id=:id AND published=true FOR UPDATE")
                .bind("id",entity.id()).fetch().one()
                .filter(row->entity.kind().equals(row.get("entity_kind"))&&entity.name().equals(row.get("canonical_name")))
                .flatMap(row->Flux.fromIterable(entity.identifiers()).concatMap(identifier->
                    db.sql("SELECT entity_id FROM knowledge_identifier WHERE namespace=:namespace AND external_id=:external FOR UPDATE")
                        .bind("namespace",identifier.namespace()).bind("external",identifier.value())
                        .map((r,m)->entity.id().equals(r.get("entity_id",String.class))).one().defaultIfEmpty(false))
                    .all(Boolean::booleanValue).filter(Boolean::booleanValue).map(ignored->entity.id())))
            .collect(java.util.stream.Collectors.toSet());
    }
    Mono<Void> register(KnowledgeBatch.Entity entity,String batch) {
        return db.sql("SELECT entity_kind FROM knowledge_entity WHERE entity_id=:id FOR UPDATE").bind("id",entity.id()).fetch().one()
            .flatMap(row->entity.kind().equals(row.get("entity_kind"))?Mono.<Void>empty():Mono.error(conflict("entity kind cannot change")))
            .then(db.sql("INSERT INTO knowledge_entity(entity_id,entity_kind,canonical_name,published) VALUES(:id,:kind,:name,true) ON DUPLICATE KEY UPDATE canonical_name=VALUES(canonical_name),published=true")
                .bind("id",entity.id()).bind("kind",entity.kind()).bind("name",entity.name()).fetch().rowsUpdated())
            .thenMany(Flux.fromIterable(entity.identifiers()).concatMap(i->registerIdentifier(i,entity.id(),batch,entity.kind().equals("person"))))
            .then(entity.kind().equals("person")?alias(entity.id(),entity.id()):Mono.empty());
    }
    private Mono<Void> registerIdentifier(KnowledgeBatch.Identifier i,String entity,String batch,boolean person) {
        return db.sql("INSERT IGNORE INTO knowledge_identifier(namespace,external_id,entity_id,evidence_batch_id) VALUES(:namespace,:external,:entity,:batch)")
            .bind("namespace",i.namespace()).bind("external",i.value()).bind("entity",entity).bind("batch",batch).fetch().rowsUpdated()
            .then(db.sql("SELECT entity_id FROM knowledge_identifier WHERE namespace=:namespace AND external_id=:external FOR UPDATE")
                .bind("namespace",i.namespace()).bind("external",i.value()).map((r,m)->r.get("entity_id",String.class)).one())
            .filter(entity::equals).switchIfEmpty(Mono.error(conflict("identifier already belongs to another entity"))).then()
            .thenMany(person?db.sql("SELECT identity_key FROM parliament_person_identifier WHERE identifier_namespace=:namespace AND external_id=:external")
                .bind("namespace",i.namespace()).bind("external",i.value()).map((r,m)->r.get("identity_key",String.class)).all()
                .concatMap(key->bind(key,entity,batch)):Flux.empty()).then();
    }
    static ResponseStatusException conflict(String message) { return new ResponseStatusException(HttpStatus.CONFLICT,message); }
}
