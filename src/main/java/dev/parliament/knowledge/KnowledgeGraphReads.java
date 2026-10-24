package dev.parliament.knowledge;

import com.fasterxml.jackson.databind.ObjectMapper;
import dev.parliament.tracking.TrackingPolicy;
import java.nio.charset.StandardCharsets;
import java.time.*;
import java.util.*;
import org.springframework.r2dbc.core.DatabaseClient;
import org.springframework.r2dbc.connection.R2dbcTransactionManager;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.support.DefaultTransactionDefinition;
import org.springframework.transaction.reactive.TransactionalOperator;
import reactor.core.publisher.Mono;
import static dev.parliament.knowledge.KnowledgeGraphProfiles.*;

/** Bounded breadth-first traversal and cursor directory over the existing relational indices. */
public final class KnowledgeGraphReads {
    private record DirectoryRow(String id,String name) {}
    private record Walk(String root,Set<String> selected,Set<String> frontier,int remaining,int limit,String type,
            Map<String,Revision> revisions,boolean truncated,long deadline) {}
    private final DatabaseClient db;
    private final KnowledgeJson json;
    private final KnowledgeIdentity identities;
    private final KnowledgeRepository repository;
    private final KnowledgeGraphClosure closure;
    private final TransactionalOperator readTransaction;
    public KnowledgeGraphReads(DatabaseClient db,ObjectMapper mapper,KnowledgeIdentity identities,KnowledgeRepository repository) {
        this.db=db;json=new KnowledgeJson(mapper);this.identities=identities;this.repository=repository;
        closure=new KnowledgeGraphClosure(db,json);
        var definition=new DefaultTransactionDefinition();definition.setReadOnly(true);
        definition.setIsolationLevel(TransactionDefinition.ISOLATION_REPEATABLE_READ);
        readTransaction=TransactionalOperator.create(new R2dbcTransactionManager(db.getConnectionFactory()),definition);
    }

    public Mono<KnowledgeGraph> graph(String rootId,String rootKind,int depth,int limit,String relationType) {
        validate(rootId,rootKind,depth,limit,relationType);
        return KnowledgeGraphLimits.timed(readTransaction.transactional(Mono.defer(()->{
            long deadline=KnowledgeGraphLimits.deadline();
            return (rootKind.equals("person")?identities.resolve(rootId):Mono.just(rootId)).flatMap(id->{
                String root=rootKind+":"+id;
                return walk(new Walk(root,new LinkedHashSet<>(List.of(root)),Set.of(root),depth,limit,relationType,new LinkedHashMap<>(),false,deadline));
            });
        })));
    }
    public Mono<KnowledgeGraph> candidate(String batchId) {
        TrackingPolicy.id(batchId);
        return repository.get(batchId).map(saved->{
            var data=KnowledgeGraphProjection.build(List.of(new Revision(saved.batch(),saved.reviewedAt())),Set.of(),true);
            var selected=data.nodes().keySet().stream().sorted().limit(100).collect(java.util.stream.Collectors.toCollection(LinkedHashSet::new));
            KnowledgePolicy.require(!selected.isEmpty(),"candidate graph has no nodes");
            String root=selected.stream().filter(k->k.startsWith("person:")).findFirst().orElse(selected.iterator().next());
            return result(root,selected,data,data.nodes().size()>selected.size(),"candidate");
        });
    }
    private Mono<KnowledgeGraph> walk(Walk state) {
        List<String> ids=state.frontier().stream().map(k->k.substring(k.indexOf(':')+1)).distinct().toList();
        return revisions(ids).flatMap(revisions->{
            revisions.forEach(r->state.revisions().put(r.batch().id(),r));
            if(state.revisions().size()>KnowledgeGraphLimits.REVISIONS||state.revisions().values().stream().mapToLong(Revision::bytes).sum()>KnowledgeGraphLimits.BYTES)
                return Mono.error(KnowledgeGraphLimits.exceeded());
            return closure.complete(state.revisions(),state.deadline()).then(Mono.defer(()->publishedEvents(new ArrayList<>(state.revisions().keySet())))).flatMap(events->{
                var data=KnowledgeGraphProjection.build(new ArrayList<>(state.revisions().values()),events,false,state.deadline());
                return ensureRoot(state.root(),data).flatMap(complete->{
                Set<String> selected=new LinkedHashSet<>(state.selected());Set<String> next=new LinkedHashSet<>();
                boolean truncated=state.truncated();
                List<KnowledgeGraph.Edge> adjacent=complete.edges().stream().filter(e->state.type()==null||e.type().equals(state.type()))
                        .filter(e->state.frontier().contains(e.sourceKey())||state.frontier().contains(e.targetKey()))
                        .sorted(Comparator.comparing(KnowledgeGraph.Edge::type).thenComparing(KnowledgeGraph.Edge::id)).toList();
                for(var edge:adjacent) {
                    for(String key:List.of(edge.sourceKey(),edge.targetKey()))if(!selected.contains(key)) {
                        if(selected.size()==state.limit())truncated=true;
                        else {selected.add(key);next.add(key);}
                    }
                }
                var filtered=new KnowledgeGraphProjection.Data(complete.nodes(),complete.edges().stream().filter(e->state.type()==null||e.type().equals(state.type())).toList());
                if(state.remaining()==1||next.isEmpty())return Mono.just(result(state.root(),selected,filtered,truncated,"published"));
                return walk(new Walk(state.root(),selected,next,state.remaining()-1,state.limit(),state.type(),state.revisions(),truncated,state.deadline()));
                });
            });
        });
    }
    private Mono<KnowledgeGraphProjection.Data> ensureRoot(String root,KnowledgeGraphProjection.Data data) {
        if(data.nodes().containsKey(root))return Mono.just(data);
        String kind=root.substring(0,root.indexOf(':')),id=root.substring(root.indexOf(':')+1);
        if(!Set.of("person","organization","bill","policy").contains(kind))return Mono.error(KnowledgeRepository.notFound());
        return db.sql("SELECT canonical_name FROM knowledge_entity WHERE entity_id=:id AND entity_kind=:kind AND published=true")
                .bind("id",id).bind("kind",kind).map((r,m)->r.get("canonical_name",String.class)).one().switchIfEmpty(Mono.error(KnowledgeRepository.notFound()))
                .map(name->{
                    Map<String,KnowledgeGraph.Node> nodes=new LinkedHashMap<>(data.nodes());
                    String href=kind.equals("person")?"/people/"+id:kind.equals("bill")?"/bills/"+id:"/explore?rootKind="+kind+"&rootId="+id;
                    nodes.put(root,new KnowledgeGraph.Node(root,id,kind,name,href,null));
                    return new KnowledgeGraphProjection.Data(nodes,data.edges());
                });
    }
    private KnowledgeGraph result(String root,Set<String> selected,KnowledgeGraphProjection.Data data,boolean truncated,String visibility) {
        var edges=data.edges().stream().filter(e->selected.contains(e.sourceKey())&&selected.contains(e.targetKey()))
                .sorted(Comparator.comparing(KnowledgeGraph.Edge::type).thenComparing(KnowledgeGraph.Edge::id)).toList();
        boolean edgeLimit=edges.size()>1000;
        List<KnowledgeGraph.Node> nodes=selected.stream().map(data.nodes()::get).filter(Objects::nonNull)
                .sorted(Comparator.comparing(n->n.key().equals(root)?"":n.key())).toList();
        return new KnowledgeGraph(root,nodes,edgeLimit?edges.subList(0,1000):edges,truncated||edgeLimit,visibility);
    }
    private Mono<List<Revision>> revisions(List<String> ids) {
        if(ids.isEmpty())return Mono.just(List.of());
        var query=db.sql("""
                SELECT b.payload,b.reviewed_at FROM knowledge_batch b WHERE b.review_state='published' AND (
                  b.issue_id IN (:ids) OR
                  EXISTS(SELECT 1 FROM knowledge_entity_version e WHERE e.batch_id=b.batch_id AND e.entity_id IN (:ids)) OR
                  EXISTS(SELECT 1 FROM knowledge_relation r WHERE r.batch_id=b.batch_id AND (r.subject_id IN (:ids) OR r.object_id IN (:ids))) OR
                  EXISTS(SELECT 1 FROM knowledge_context c WHERE c.batch_id=b.batch_id AND c.event_id IN (:ids)) OR
                  EXISTS(SELECT 1 FROM JSON_TABLE(b.payload,'$.documents[*]' COLUMNS(document_id VARCHAR(128) PATH '$.id')) d WHERE d.document_id IN (:ids)))
                ORDER BY b.reviewed_at DESC,b.batch_id DESC LIMIT :budget
                """).bind("ids",ids).bind("budget",KnowledgeGraphLimits.REVISIONS+1);
        return KnowledgeGraphLimits.read(query,json);
    }
    private Mono<Set<String>> publishedEvents(List<String> batches) {
        if(batches.isEmpty())return Mono.just(Set.of());
        return db.sql("""
                SELECT c.event_id,c.event_version FROM knowledge_context c
                JOIN knowledge_batch b ON b.batch_id=c.batch_id
                JOIN tracking_event e ON e.event_id=c.event_id AND e.latest_version=c.event_version
                JOIN tracking_event_version v ON v.event_id=c.event_id AND v.version_id=c.event_version
                WHERE c.batch_id IN (:batches) AND b.review_state='published' AND v.review_state='published'
                """).bind("batches",batches).map((r,m)->r.get("event_id",String.class)+":"+r.get("event_version",String.class))
                .all().collect(java.util.stream.Collectors.toSet());
    }
    public Mono<KnowledgeGraph.People> people(String cursor,String query,String organizationId,int limit) {
        KnowledgePolicy.require(limit>=1&&limit<=100,"limit must be 1..100");
        if(query!=null)text(query,100,"query");if(organizationId!=null)TrackingPolicy.id(organizationId);
        DirectoryRow after=cursor==null?null:decode(cursor,query,organizationId);
        return KnowledgeGraphLimits.timed(readTransaction.transactional(Mono.defer(()->scan(after,query,organizationId,limit,0,KnowledgeGraphLimits.deadline(),new ArrayList<>())).map(items->{
            boolean more=items.size()>limit;
            List<KnowledgeGraph.Person> visible=List.copyOf(more?items.subList(0,limit):items);
            String next=more?encode(visible.get(visible.size()-1),query,organizationId):null;
            return new KnowledgeGraph.People(visible,next);
        })));
    }
    private Mono<List<KnowledgeGraph.Person>> scan(DirectoryRow after,String query,String organization,int limit,int scanned,long deadline,List<KnowledgeGraph.Person> found) {
        String tail=after==null?"":" AND (canonical_name>:afterName OR (canonical_name=:afterName AND entity_id>:afterId))";
        String organizationFilter=organization==null?"":"""
                 AND EXISTS(SELECT 1 FROM knowledge_entity_version ev JOIN knowledge_batch b ON b.batch_id=ev.batch_id
                   WHERE ev.entity_id=knowledge_entity.entity_id AND b.review_state='published'
                   AND JSON_CONTAINS(JSON_EXTRACT(ev.payload,'$.tenures'),JSON_OBJECT('organizationId',:organization)))
                """;
        var sql=db.sql("SELECT entity_id,canonical_name FROM knowledge_entity WHERE entity_kind='person' AND published=true AND canonical_name LIKE :pattern"+tail+organizationFilter+" ORDER BY canonical_name,entity_id LIMIT 100")
                .bind("pattern",query==null?"%":"%"+query.replace("\\","\\\\").replace("%","\\%").replace("_","\\_")+"%");
        if(after!=null)sql=sql.bind("afterName",after.name()).bind("afterId",after.id());
        if(organization!=null)sql=sql.bind("organization",organization);
        return sql.map((r,m)->new DirectoryRow(r.get("entity_id",String.class),r.get("canonical_name",String.class))).all().collectList().flatMap(rows->{
            if(rows.isEmpty())return Mono.just(found);
            if(scanned+rows.size()>KnowledgeGraphLimits.PEOPLE_SCANNED)return Mono.error(KnowledgeGraphLimits.exceeded());
            return entityRevisions(rows.stream().map(DirectoryRow::id).toList()).flatMap(revisions->{
                for(DirectoryRow row:rows) {
                    KnowledgeGraphLimits.checkTime(deadline);
                    Snapshot profile=merge(row.id(),revisions,deadline);
                    OfficeClaim office=profile.offices().stream().filter(o->currentOffice(o.tenure())
                                    &&confirmedCurrentSource(o,profile.facts())
                                    &&(organization==null||organization.equals(o.tenure().organizationId())))
                            .sorted(Comparator.comparing((OfficeClaim o)->o.tenure().observedAt()).reversed()
                                    .thenComparing(o->o.tenure().organizationId()).thenComparing(o->o.tenure().position())).findFirst().orElse(null);
                    if(organization!=null&&(office==null||!organization.equals(office.tenure().organizationId())))continue;
                    Instant observed=office==null?latestObservedAt(row.id(),revisions):office.tenure().observedAt();
                    found.add(new KnowledgeGraph.Person(row.id(),row.name(),"person",office==null?null:office.tenure().position(),
                            office==null?null:office.tenure().organizationId(),office==null?null:office.organizationName(),observed));
                    if(found.size()>limit)return Mono.just(found);
                }
                return rows.size()<100?Mono.just(found):scan(rows.get(rows.size()-1),query,organization,limit,scanned+rows.size(),deadline,found);
            });
        });
    }
    private Mono<List<Revision>> entityRevisions(List<String> ids) {
        var query=db.sql("""
                SELECT DISTINCT b.payload,b.reviewed_at,b.batch_id FROM knowledge_batch b
                JOIN knowledge_entity_version e ON e.batch_id=b.batch_id
                WHERE b.review_state='published' AND e.entity_id IN (:ids)
                ORDER BY b.reviewed_at DESC,b.batch_id DESC LIMIT :budget
                """).bind("ids",ids).bind("budget",KnowledgeGraphLimits.REVISIONS+1);
        return KnowledgeGraphLimits.read(query,json);
    }
    private boolean currentOffice(KnowledgeBatch.Tenure tenure) {
        LocalDate observed=tenure.observedAt().atZone(ZoneId.of("Asia/Seoul")).toLocalDate();
        return (tenure.validFrom()==null||!tenure.validFrom().isAfter(observed))
                &&(tenure.validUntil()==null||!tenure.validUntil().isBefore(LocalDate.now(ZoneId.of("Asia/Seoul"))));
    }
    private Instant latestObservedAt(String id,List<Revision> revisions) {
        return revisions.stream().filter(r->r.batch().entities().stream().anyMatch(e->e.id().equals(id)))
                .flatMap(r->r.batch().documents().stream()).map(d->d.observedAt()==null?d.collectedAt():d.observedAt()).max(Comparator.naturalOrder()).orElse(null);
    }
    private String encode(KnowledgeGraph.Person last,String query,String organization) {
        return Base64.getUrlEncoder().withoutPadding().encodeToString(json.write(List.of(last.name(),last.id(),scope(query,organization))).getBytes(StandardCharsets.UTF_8));
    }
    private DirectoryRow decode(String cursor,String query,String organization) {
        try {
            KnowledgePolicy.require(cursor.length()<=3000,"invalid people cursor");
            List<?> value=json.read(new String(Base64.getUrlDecoder().decode(cursor),StandardCharsets.UTF_8),List.class);
            KnowledgePolicy.require(value.size()==3&&Objects.equals(value.get(2),scope(query,organization)),"invalid people cursor scope");
            String name=(String)value.get(0),id=(String)value.get(1);text(name,500,"cursor name");TrackingPolicy.id(id);
            return new DirectoryRow(id,name);
        } catch(RuntimeException e) {throw new IllegalArgumentException("invalid people cursor");}
    }
    private String scope(String query,String organization) {return KnowledgeJson.hash((query==null?"":query)+"\u0000"+(organization==null?"":organization));}
    private void text(String value,int max,String field) {KnowledgePolicy.require(value!=null&&value.length()<=max&&value.indexOf('\0')<0,"invalid "+field);}
    private void validate(String id,String kind,int depth,int limit,String type) {
        TrackingPolicy.id(id);KnowledgePolicy.require(KnowledgeGraphProjection.KINDS.contains(kind),"unsupported root kind");
        KnowledgePolicy.require(depth>=1&&depth<=2,"depth must be 1..2");KnowledgePolicy.require(limit>=2&&limit<=100,"limit must be 2..100");
        KnowledgePolicy.require(type==null||KnowledgeGraphProjection.TYPES.contains(type),"unsupported relationship filter");
    }
}
