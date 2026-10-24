package dev.parliament.knowledge;

import com.fasterxml.jackson.databind.ObjectMapper;
import dev.parliament.tracking.Activity;
import dev.parliament.tracking.TrackingPolicy;
import dev.parliament.tracking.TrackingRepository;
import org.springframework.r2dbc.core.DatabaseClient;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;
import java.time.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import static dev.parliament.knowledge.KnowledgeBatch.*;

/** Public knowledge is gated by reviewed batch and the exact published event version. */
public final class KnowledgeReads {
    public record Participant(String personId,String name,String role,List<String> evidenceIds,String organizationAtTime,String positionAtTime) {}
    public record PublicEvidence(String id,String documentId,String documentVersion,String extractionVersion,String segmentId,
            int start,int end,String excerpt,String before,String after,List<Mention> mentions,String sourceUrl,String title,String locator) {}
    public record PublicContext(String eventId,String eventVersion,String changeKind,Activity activity,List<Participant> participants,
            List<Relation> relations,List<PublicEvidence> evidence,List<Map<String,Object>> documents,String dateKind,
            Instant scheduledAt,String scheduledPrecision) {}
    public record Profile(String id,String name,String kind,List<Fact> facts,List<Map<String,Object>> tenures,List<Map<String,String>> relatedIssues,List<PublicContext> activities) {}
    public record Lineage(String id,List<Relation> items) {}
    public record Timeline(String id,List<PublicContext> items,String nextCursor) {}
    private record ContextRow(KnowledgeBatch batch,Context context,Instant at,String dateKind) {}
    private final DatabaseClient db;
    private final KnowledgeJson json;
    private final TrackingRepository tracking;
    private final KnowledgeIdentity ids;
    private final KnowledgeGraphProfiles profiles;
    public KnowledgeReads(DatabaseClient db,ObjectMapper mapper,TrackingRepository tracking,KnowledgeIdentity ids) {
        this.db=db;json=new KnowledgeJson(mapper);this.tracking=tracking;this.ids=ids;profiles=new KnowledgeGraphProfiles(db,mapper);
    }
    public Mono<PublicContext> context(String id,String version) {
        TrackingPolicy.id(id); if(version!=null)TrackingPolicy.id(version);
        String extra=version==null?" AND e.latest_version=c.event_version":" AND c.event_version=:version";
        var q=db.sql(baseContext()+" WHERE c.event_id=:id AND b.review_state='published' AND v.review_state='published'"+extra+" ORDER BY b.reviewed_at DESC LIMIT 1").bind("id",id);
        if(version!=null)q=q.bind("version",version);
        return q.map((r,m)->row(r)).one().switchIfEmpty(Mono.error(KnowledgeRepository.notFound())).flatMap(this::publicContext);
    }
    public Mono<Profile> profile(String id) {
        TrackingPolicy.id(id);
        return ids.resolve(id).flatMap(canonical->db.sql("SELECT canonical_name,entity_kind FROM knowledge_entity WHERE entity_id=:id AND entity_kind='person' AND published=true")
            .bind("id",canonical).fetch().one().switchIfEmpty(Mono.error(KnowledgeRepository.notFound())).flatMap(person->
                profiles.snapshot(canonical).flatMap(snapshot->{
                    List<Fact> facts=snapshot.facts().stream().map(KnowledgeGraphProfiles.FactClaim::fact).toList();
                    List<Map<String,Object>> tenures=snapshot.offices().stream().map(claim->{
                        Map<String,Object> out=json.map(claim.tenure());out.put("organizationName",claim.organizationName());return out;
                    }).toList();
                    return personContexts(canonical).collectList().flatMap(rows->{
                        List<Map<String,String>> issues=rows.stream().map(r->Map.of("id",r.batch().issueId(),"title",issueTitle(r.batch().issueId()))).distinct().toList();
                        return Flux.fromIterable(rows).concatMap(this::publicContext).collectList()
                                .map(contexts->new Profile(canonical,(String)person.get("canonical_name"),"person",facts,tenures,issues,contexts));
                    });
                })));
    }
    private String issueTitle(String id) { try{return new dev.parliament.tracking.TrackingIssues().find(id).title();}catch(Exception e){return id;} }
    public Mono<Timeline> personTimeline(String id,String cursor,int limit,String order,String from,String until,String role) {
        TrackingPolicy.id(id);KnowledgePolicy.require(limit>=1&&limit<=100,"limit must be 1..100");
        KnowledgePolicy.require(Set.of("newest","oldest").contains(order),"unsupported timeline order");
        KnowledgePolicy.require(role==null||Set.of("lead_sponsor","co_sponsor","speaker","voter","scheduled_participant").contains(role),"unsupported role");
        LocalDate first=timelineDate(from),last=timelineDate(until);
        KnowledgePolicy.require(first==null||last==null||!first.isAfter(last),"invalid timeline period");
        return ids.resolve(id).flatMap(person->db.sql("SELECT entity_id FROM knowledge_entity WHERE entity_id=:id AND entity_kind='person' AND published=true")
            .bind("id",person).fetch().one().switchIfEmpty(Mono.error(KnowledgeRepository.notFound())).flatMap(found->{
                String scope=KnowledgeJson.hash(String.join("|",person,order,from==null?"":from,until==null?"":until,role==null?"":role));
                String[] parts=personCursor(cursor,scope);
                String direction=order.equals("newest")?"DESC":"ASC",operator=order.equals("newest")?"<":">";
                String tail=parts==null?"":" AND (c.sort_at"+operator+":at OR (c.sort_at=:at AND c.event_id"+operator+":cursorId) OR (c.sort_at=:at AND c.event_id=:cursorId AND c.event_version"+operator+":cursorVersion))";
                String roleFilter=role==null?"":"""
                    AND EXISTS(SELECT 1 FROM knowledge_relation r
                        WHERE r.batch_id=b.batch_id AND r.decision='approved' AND r.relation_type=:role AND
                    """+ids.matches("r.subject_id",":person")+" AND (r.object_id=c.event_id OR r.object_id=v.bill_id) AND JSON_CONTAINS(JSON_EXTRACT(c.payload,'$.relationIds'),JSON_QUOTE(r.relation_id)))";
                var query=db.sql(baseContext()+" WHERE b.review_state='published' AND v.review_state='published' AND e.latest_version=c.event_version AND EXISTS(SELECT 1 FROM tracking_event_person p WHERE p.event_id=c.event_id AND p.version_id=c.event_version AND "+ids.matches("p.person_id",":person")+")"
                    +(first==null?"":" AND c.sort_at>=:first")+(last==null?"":" AND c.sort_at<:last")+" "+roleFilter+tail
                    +" ORDER BY c.sort_at "+direction+",c.event_id "+direction+",c.event_version "+direction+" LIMIT :limit")
                    .bind("person",person).bind("limit",limit+1);
                if(first!=null)query=query.bind("first",first.atStartOfDay(ZoneId.of("Asia/Seoul")).toInstant());
                if(last!=null)query=query.bind("last",last.plusDays(1).atStartOfDay(ZoneId.of("Asia/Seoul")).toInstant());
                if(role!=null)query=query.bind("role",role);
                if(parts!=null)query=query.bind("at",Instant.parse(parts[0])).bind("cursorId",parts[1]).bind("cursorVersion",parts[2]);
                return query.map((row,metadata)->row(row)).all().collectList().flatMap(rows->{
                    boolean more=rows.size()>limit;var visible=more?rows.subList(0,limit):rows;
                    String next=null;
                    if(more) {var item=visible.get(visible.size()-1);next=Base64.getUrlEncoder().withoutPadding().encodeToString((item.at()+"|"+item.context().eventId()+"|"+item.context().eventVersion()+"|"+scope).getBytes(StandardCharsets.UTF_8));}
                    final String nextCursor=next;
                    return Flux.fromIterable(visible).concatMap(this::publicContext).collectList().map(items->new Timeline(person,items,nextCursor));
                });
            }));
    }
    private LocalDate timelineDate(String value) {
        if(value==null)return null;
        try {KnowledgePolicy.require(value.matches("[0-9]{4}-[0-9]{2}-[0-9]{2}"),"invalid timeline date");return LocalDate.parse(value);}
        catch(DateTimeException error){throw new IllegalArgumentException("invalid timeline date");}
    }
    private String[] personCursor(String cursor,String scope) {
        if(cursor==null)return null;
        try {
            KnowledgePolicy.require(cursor.length()<=600,"invalid person cursor");
            var parts=new String(Base64.getUrlDecoder().decode(cursor),StandardCharsets.UTF_8).split("\\|",-1);
            KnowledgePolicy.require(parts.length==4&&parts[3].equals(scope),"cursor does not match timeline filters");
            Instant.parse(parts[0]);TrackingPolicy.id(parts[1]);TrackingPolicy.id(parts[2]);return parts;
        } catch(RuntimeException error){throw new IllegalArgumentException("invalid person cursor");}
    }
    private Flux<ContextRow> personContexts(String id) {
        return db.sql(baseContext()+" WHERE b.review_state='published' AND v.review_state='published' AND e.latest_version=c.event_version AND EXISTS(SELECT 1 FROM tracking_event_person p WHERE p.event_id=c.event_id AND p.version_id=c.event_version AND "+ids.matches("p.person_id",":person")+") ORDER BY c.sort_at DESC,c.event_id DESC LIMIT 100")
            .bind("person",id).map((r,m)->row(r)).all();
    }
    public Mono<Map<String,Object>> document(String id,String version) { return document(id,version,null); }
    public Mono<Map<String,Object>> document(String id,String version,String extraction) {
        TrackingPolicy.id(id); if(version!=null)KnowledgePolicy.require(version.matches("[a-f0-9]{64}"),"invalid document version");if(extraction!=null)TrackingPolicy.id(extraction);
        return db.sql("SELECT payload FROM knowledge_batch WHERE review_state='published' AND JSON_SEARCH(payload,'one',:id,NULL,'$.documents[*].id') IS NOT NULL ORDER BY reviewed_at DESC,batch_id DESC")
            .bind("id",id).map((r,m)->json.read(r.get("payload",String.class),KnowledgeBatch.class)).all()
            .concatMapIterable(KnowledgeBatch::documents).filter(d->d.id().equals(id)&&(version==null||d.version().equals(version))&&(extraction==null||d.extractionVersion().equals(extraction)))
            .next().flatMap(d->db.sql("SELECT MAX(observed_at) AS latest FROM knowledge_document_observation WHERE document_id=:id AND version_id=:version")
                    .bind("id",d.id()).bind("version",d.version()).map((r,m)->java.util.Optional.ofNullable(r.get("latest",Instant.class))).one()
                    .map(at->{Map<String,Object> out=publicDocument(d);at.ifPresent(value->out.put("observedAt",value.toString()));return out;}))
            .switchIfEmpty(Mono.error(KnowledgeRepository.notFound()));
    }
    public Mono<PublicEvidence> evidence(String id) {
        TrackingPolicy.id(id);
        return db.sql("SELECT b.payload FROM knowledge_evidence x JOIN knowledge_evidence_registry fixed ON fixed.evidence_id=x.evidence_id JOIN knowledge_batch b ON b.batch_id=x.batch_id WHERE x.evidence_id=:id AND b.review_state='published' ORDER BY b.reviewed_at DESC LIMIT 1")
            .bind("id",id).map((r,m)->json.read(r.get("payload",String.class),KnowledgeBatch.class)).one()
            .flatMap(b->{var e=b.evidence().stream().filter(x->x.id().equals(id)).findFirst().orElseThrow();return KnowledgePolicy.usable(b,e)?Mono.just(publicEvidence(b,e)):Mono.empty();})
            .switchIfEmpty(Mono.error(KnowledgeRepository.notFound()));
    }
    public Mono<Lineage> lineage(String id) {
        TrackingPolicy.id(id);
        return db.sql("""
                SELECT payload FROM (
                  SELECT r.payload,r.decision,r.subject_id,r.object_id,
                    ROW_NUMBER() OVER(PARTITION BY r.subject_id,r.object_id,r.relation_type
                      ORDER BY b.reviewed_at DESC,b.batch_id DESC,r.relation_id DESC) AS edge_rank
                  FROM knowledge_relation r JOIN knowledge_batch b ON b.batch_id=r.batch_id
                  WHERE b.review_state='published' AND r.relation_type='incorporated_into_alternative'
                    AND (r.subject_id=:id OR r.object_id=:id)
                ) current_edges WHERE edge_rank=1 AND decision='approved'
                ORDER BY subject_id,object_id LIMIT 100
                """).bind("id",id).map((r,m)->json.read(r.get("payload",String.class),Relation.class)).all()
                .collectList().map(items->new Lineage(id,items));
    }
    public Mono<Timeline> timeline(String issue,String cursor,int limit) {
        TrackingPolicy.id(issue);KnowledgePolicy.require(limit>=1&&limit<=100,"limit must be 1..100");
        String[] parts=cursor==null?null:decode(cursor);
        String tail=parts==null?"":" AND (c.sort_at<:at OR (c.sort_at=:at AND c.event_id<:cursorId) OR (c.sort_at=:at AND c.event_id=:cursorId AND c.event_version<:cursorVersion))";
        var q=db.sql(baseContext()+" WHERE c.issue_id=:issue AND b.review_state='published' AND v.review_state='published' AND e.latest_version=c.event_version"+tail+" ORDER BY c.sort_at DESC,c.event_id DESC,c.event_version DESC LIMIT :limit").bind("issue",issue).bind("limit",limit+1);
        if(parts!=null)q=q.bind("at",Instant.parse(parts[0])).bind("cursorId",parts[1]).bind("cursorVersion",parts[2]);
        return q.map((r,m)->row(r)).all().collectList().flatMap(rows->{
            boolean more=rows.size()>limit;var visible=more?rows.subList(0,limit):rows;
            String next=more?encode(visible.get(visible.size()-1)):null;
            return Flux.fromIterable(visible).concatMap(this::publicContext).collectList().map(items->new Timeline(issue,items,next));
        });
    }
    private Mono<PublicContext> publicContext(ContextRow row) {
        KnowledgeBatch b=row.batch();Context c=row.context();
        return tracking.detail(c.eventId(),c.eventVersion()).map(activity->{
            List<Relation> relations=b.relations().stream().filter(r->c.relationIds().contains(r.id())&&r.decision().equals("approved")&&allowedEvidence(b,r.evidenceIds())).toList();
            List<Participant> participants=relations.stream().filter(r->Set.of("lead_sponsor","co_sponsor","speaker","voter","scheduled_participant").contains(r.type())&&(r.objectId().equals(activity.id())||r.objectId().equals(activity.billId())))
                .map(r->participant(b,c,r,activity)).toList();
            List<PublicEvidence> evidence=b.evidence().stream().filter(e->(c.evidenceIds().contains(e.id())||relations.stream().anyMatch(r->r.evidenceIds().contains(e.id())))&&KnowledgePolicy.usable(b,e)).map(e->publicEvidence(b,e)).toList();
            List<Map<String,Object>> docs=b.documents().stream().filter(d->c.documentIds().contains(d.id())).map(this::publicDocument).toList();
            return new PublicContext(c.eventId(),c.eventVersion(),c.changeKind(),activity,participants,relations,evidence,docs,row.dateKind(),c.scheduledAt(),c.scheduledPrecision());
        });
    }
    private Participant participant(KnowledgeBatch b,Context c,Relation r,Activity a) {
        Entity person=b.entities().stream().filter(e->e.id().equals(r.subjectId())).findFirst().orElseThrow();
        LocalDate date=(a.occurredAt()==null?a.publishedAt():a.occurredAt()).atZone(ZoneId.of("Asia/Seoul")).toLocalDate();
        Tenure tenure=person.tenures().stream().filter(t->tenureAtEvent(t,c,r,date)
                &&allowedEvidence(b,t.evidenceIds())).findFirst().orElse(null);
        return new Participant(person.id(),person.name(),r.type(),r.evidenceIds(),tenure==null?null:name(b,tenure.organizationId()),tenure==null?null:tenure.position());
    }
    private boolean tenureAtEvent(Tenure t,Context c,Relation r,LocalDate date) {
        LocalDate observed=t.observedAt().atZone(ZoneId.of("Asia/Seoul")).toLocalDate();
        if(t.validFrom()!=null)return !date.isBefore(t.validFrom())&&!date.isAfter(t.validUntil()==null?observed:t.validUntil());
        boolean eventEvidence=t.evidenceIds().stream().anyMatch(id->c.evidenceIds().contains(id)||r.evidenceIds().contains(id));
        return eventEvidence&&date.equals(observed)&&(t.validUntil()==null||!date.isAfter(t.validUntil()));
    }
    private PublicEvidence publicEvidence(KnowledgeBatch b,Evidence e) {
        Document d=b.documents().stream().filter(x->x.id().equals(e.documentId())&&x.version().equals(e.documentVersion())&&x.extractionVersion().equals(e.extractionVersion())).findFirst().orElseThrow();
        Segment s=d.segments().stream().filter(x->x.id().equals(e.segmentId())).findFirst().orElseThrow();
        int count=s.text().codePointCount(0,s.text().length());
        String before=e.start()==0?"":KnowledgePolicy.slice(s.text(),Math.max(0,e.start()-300),e.start());
        String after=e.end()==count?"":KnowledgePolicy.slice(s.text(),e.end(),Math.min(count,e.end()+300));
        int segmentIndex=d.segments().indexOf(s);
        if(e.start()==0&&segmentIndex>0) {
            String previous=d.segments().get(segmentIndex-1).text();int size=previous.codePointCount(0,previous.length());
            before=KnowledgePolicy.slice(previous,Math.max(0,size-299),size)+"\n";
        }
        if(e.end()==count&&segmentIndex+1<d.segments().size()) {
            String next=d.segments().get(segmentIndex+1).text();int size=next.codePointCount(0,next.length());
            after="\n"+KnowledgePolicy.slice(next,0,Math.min(299,size));
        }
        return new PublicEvidence(e.id(),e.documentId(),e.documentVersion(),e.extractionVersion(),e.segmentId(),e.start(),e.end(),KnowledgePolicy.slice(s.text(),e.start(),e.end()),before,after,
                s.mentions().stream().map(this::publicMention).toList(),d.sourceUrl(),d.title(),s.locator());
    }
    private Mention publicMention(Mention m) { return m.decision().equals("approved")?new Mention(m.id(),m.surface(),m.start(),m.end(),List.of(),m.personId(),m.decision()):new Mention(m.id(),m.surface(),m.start(),m.end(),List.of(),null,m.decision()); }
    private Map<String,Object> publicDocument(Document d) {
        Map<String,Object> out=json.map(d);out.remove("rawStorageKey");out.remove("observationId");out.remove("transitionId");
        out.put("segments",d.licenseStatus().equals("allowed")?d.segments().stream().map(s->new Segment(s.id(),s.text(),s.locator(),s.mentions().stream().map(this::publicMention).toList())).toList():List.of());
        return out;
    }
    private boolean allowedEvidence(KnowledgeBatch b,List<String> refs) { return refs!=null&&!refs.isEmpty()&&refs.stream().allMatch(id->b.evidence().stream().anyMatch(e->e.id().equals(id)&&KnowledgePolicy.usable(b,e))); }
    private String name(KnowledgeBatch b,String id) { return b.entities().stream().filter(e->e.id().equals(id)).map(Entity::name).findFirst().orElse(id); }
    private String baseContext() { return "SELECT b.payload AS batch_payload,c.payload AS context_payload,c.sort_at,c.date_kind FROM knowledge_context c JOIN knowledge_batch b ON b.batch_id=c.batch_id JOIN tracking_event_version v ON v.event_id=c.event_id AND v.version_id=c.event_version JOIN tracking_event e ON e.event_id=c.event_id"; }
    private ContextRow row(io.r2dbc.spi.Row r) { return new ContextRow(json.read(r.get("batch_payload",String.class),KnowledgeBatch.class),json.read(r.get("context_payload",String.class),Context.class),r.get("sort_at",Instant.class),r.get("date_kind",String.class)); }
    private String encode(ContextRow r) { return Base64.getUrlEncoder().withoutPadding().encodeToString((r.at()+"|"+r.context().eventId()+"|"+r.context().eventVersion()).getBytes(StandardCharsets.UTF_8)); }
    private String[] decode(String cursor) {
        try { KnowledgePolicy.require(cursor.length()<=600,"invalid timeline cursor");String[] p=new String(Base64.getUrlDecoder().decode(cursor),StandardCharsets.UTF_8).split("\\|",-1);KnowledgePolicy.require(p.length==3,"invalid timeline cursor");Instant.parse(p[0]);TrackingPolicy.id(p[1]);TrackingPolicy.id(p[2]);return p; }
        catch(RuntimeException e) { throw new IllegalArgumentException("invalid timeline cursor"); }
    }
}
