package dev.parliament.knowledge;

import dev.parliament.tracking.TrackingPolicy;
import java.util.*;
import static dev.parliament.knowledge.KnowledgeBatch.*;

/** Rejects dangling evidence and unsupported actor claims before any publication. */
public final class KnowledgePolicy {
    private static final Set<String> DECISIONS = Set.of("pending", "approved", "rejected");
    private static final Set<String> PERSON_ROLES = Set.of("lead_sponsor", "co_sponsor", "speaker", "voter", "scheduled_participant");
    private static final Set<String> ORG_ROLES = Set.of("publisher", "implementing_agency", "committee_proposer");
    public void validate(KnowledgeBatch b) {
        require(b != null, "batch required");
        TrackingPolicy.id(b.id()); TrackingPolicy.id(b.issueId());
        bounded(b.entities(), 100, "entities"); bounded(b.documents(), 100, "documents");
        bounded(b.evidence(), 1000, "evidence"); bounded(b.relations(), 1000, "relations");
        bounded(b.activities(), 100, "activities"); bounded(b.contexts(), 100, "contexts");
        var entities = index(b.entities(), Entity::id);
        var docs = index(b.documents(), d -> d.id() + ":" + d.version() + ":" + d.extractionVersion());
        var evs = index(b.evidence(), Evidence::id);
        var relations = index(b.relations(), Relation::id);
        var activities = index(b.activities(), a -> a.id() + ":" + a.version());
        Set<String> ids = new HashSet<>(entities.keySet());
        b.documents().forEach(d -> ids.add(d.id())); b.activities().forEach(a -> ids.add(a.id()));
        for (Document d : b.documents()) {
            TrackingPolicy.id(d.id()); require(d.version() != null && d.version().matches("[a-f0-9]{64}"), "SHA256 document version required");
            text(d.sourceKey(),100,"source key"); text(d.recordKey(),255,"record key");
            TrackingPolicy.officialUrl(d.sourceUrl()); text(d.title(),500,"document title");
            require(Set.of("html","pdf","json","hwp","hwpx").contains(d.format()), "unsupported document format");
            require(Set.of("available","partial","unavailable","disclaimer_only","unsupported","failed").contains(d.bodyStatus()), "unsupported body status");
            require(Set.of("allowed","restricted","unknown").contains(d.licenseStatus()), "unsupported license status");
            require(d.collectedAt()!=null, "collection time required");
            require(d.datePrecision()==null || Set.of("date","second","unknown").contains(d.datePrecision()), "unsupported date precision");
            require(d.rawStorageKey()!=null && d.rawStorageKey().matches("[A-Za-z0-9_./-]{1,1024}")
                    && !d.rawStorageKey().startsWith("/") && !d.rawStorageKey().contains(".."), "unsafe raw storage key");
            TrackingPolicy.id(d.extractionVersion()); TrackingPolicy.id(d.observationId());
            if(d.transitionId()!=null) TrackingPolicy.id(d.transitionId());
            bounded(d.segments(),500,"segments"); index(d.segments(),Segment::id);
            require(d.segments().isEmpty() || Set.of("available","partial").contains(d.bodyStatus()), "unavailable body cannot have segments");
            for(Segment s:d.segments()) {
                TrackingPolicy.id(s.id()); text(s.text(),100000,"segment text"); text(s.locator(),1000,"locator");
                bounded(s.mentions(),100,"mentions"); index(s.mentions(),Mention::id);
                List<Mention> ordered=s.mentions().stream().sorted(Comparator.comparingInt(Mention::start)).toList();
                for(Mention m:ordered) {
                    TrackingPolicy.id(m.id()); decision(m.decision());
                    require(slice(s.text(),m.start(),m.end()).equals(m.surface()),"mention surface mismatch");
                    bounded(m.candidatePersonIds(),20,"candidate people");
                    m.candidatePersonIds().forEach(p -> person(entities,p));
                    if(m.personId()!=null) person(entities,m.personId());
                    require(!m.decision().equals("approved") || m.personId()!=null,"approved mention requires person");
                }
            }
        }
        for(Evidence e:b.evidence()) {
            TrackingPolicy.id(e.id());
            Document d=docs.get(e.documentId()+":"+e.documentVersion()+":"+e.extractionVersion());
            require(d!=null,"evidence document version unavailable");
            Segment s=d.segments().stream().filter(x->x.id().equals(e.segmentId())).findFirst().orElse(null);
            require(s!=null,"evidence segment unavailable"); slice(s.text(),e.start(),e.end());
        }
        for(Entity e:b.entities()) {
            TrackingPolicy.id(e.id()); require(Set.of("person","organization","bill","policy").contains(e.kind()), "unsupported entity kind");
            text(e.name(),500,"entity name"); bounded(e.identifiers(),20,"identifiers"); bounded(e.facts(),100,"facts"); bounded(e.tenures(),100,"tenures");
            for(Identifier i:e.identifiers()) { require(i.namespace()!=null&&i.namespace().matches("[A-Z0-9_]{1,64}"),"invalid identifier namespace"); text(i.value(),255,"identifier"); }
            for(Fact f:e.facts()) { text(f.label(),100,"fact label"); text(f.value(),5000,"fact value"); refs(f.evidenceIds(),evs,"fact evidence"); }
            for(Tenure t:e.tenures()) {
                require(e.kind().equals("person"),"tenure requires person");
                require(entities.containsKey(t.organizationId())&&entities.get(t.organizationId()).kind().equals("organization"),"tenure organization unavailable");
                text(t.position(),255,"position"); if(t.party()!=null) text(t.party(),255,"party");
                require(t.observedAt()!=null,"tenure observation required");
                require(t.validFrom()==null||t.validUntil()==null||!t.validFrom().isAfter(t.validUntil()),"invalid tenure range");
                refs(t.evidenceIds(),evs,"tenure evidence");
            }
        }
        Set<String> lineageEdges=new HashSet<>();
        for(Relation r:b.relations()) {
            TrackingPolicy.id(r.id()); decision(r.decision()); text(r.reason(),1000,"relation reason");
            require(ids.contains(r.subjectId())&&ids.contains(r.objectId()),"relation target unavailable");
            if(PERSON_ROLES.contains(r.type())) {
                person(entities,r.subjectId());
                boolean billRole=Set.of("lead_sponsor","co_sponsor").contains(r.type());
                require(b.activities().stream().anyMatch(a->a.id().equals(r.objectId())) || billRole&&kind(entities,r.objectId(),"bill"),"invalid person role target");
            } else if(ORG_ROLES.contains(r.type())) {
                require(kind(entities,r.subjectId(),"organization"),"organization role required");
                require(b.activities().stream().anyMatch(a->a.id().equals(r.objectId())) || kind(entities,r.objectId(),"bill") || kind(entities,r.objectId(),"policy"),"invalid organization role target");
            } else if(r.type().equals("incorporated_into_alternative")) {
                require(kind(entities,r.subjectId(),"bill")&&kind(entities,r.objectId(),"bill")&&!r.subjectId().equals(r.objectId()),"invalid bill lineage");
                require(lineageEdges.add(r.subjectId()+"|"+r.objectId()+"|"+r.type()),"duplicate bill lineage edge within one batch");
            } else if(r.type().equals("concerns")) {
                require((kind(entities,r.subjectId(),"bill")||b.activities().stream().anyMatch(a->a.id().equals(r.subjectId())))&&kind(entities,r.objectId(),"policy"),"invalid policy relationship");
            } else if(r.type().equals("records")) {
                require(b.documents().stream().anyMatch(d->d.id().equals(r.subjectId()))&&b.activities().stream().anyMatch(a->a.id().equals(r.objectId())),"invalid document relationship");
            } else throw new IllegalArgumentException("unsupported relationship");
            if(r.decision().equals("approved")) refs(r.evidenceIds(),evs,"relation evidence");
            else { bounded(r.evidenceIds(),100,"relation evidence"); r.evidenceIds().forEach(id->require(evs.containsKey(id),"relation evidence unavailable")); }
        }
        b.activities().forEach(a->new TrackingPolicy().validate(a));
        index(b.contexts(),c->c.eventId()+":"+c.eventVersion());
        require(b.contexts().size()==b.activities().size(),"each activity requires one context");
        for(Context c:b.contexts()) {
            require(activities.containsKey(c.eventId()+":"+c.eventVersion()),"context activity unavailable");
            require(Set.of("new_record","state_changed","important_correction","explanation_only","extraction_only").contains(c.changeKind()),"unsupported change kind");
            require(c.scheduledPrecision()==null||Set.of("date","second","unknown").contains(c.scheduledPrecision()),"unsupported scheduled precision");
            require(c.scheduledAt()==null||c.scheduledPrecision()!=null,"scheduled date precision required");
            require(c.scheduledAt()!=null||c.scheduledPrecision()==null||c.scheduledPrecision().equals("unknown"),"unknown scheduled date must remain null");
            refs(c.evidenceIds(),evs,"context evidence"); bounded(c.relationIds(),1000,"context relations");
            c.relationIds().forEach(id->require(relations.containsKey(id),"context relation unavailable"));
            bounded(c.documentIds(),100,"context documents");
            c.documentIds().forEach(id->require(b.documents().stream().anyMatch(d->d.id().equals(id)),"context document unavailable"));
        }
    }
    public void validatePublication(KnowledgeBatch b) {
        validatePublication(b,Set.of());
    }
    void validatePublication(KnowledgeBatch b,Set<String> verifiedExistingPeople) {
        validate(b);
        for(Document d:b.documents())for(Segment s:d.segments()) {
            int last=-1;
            for(Mention m:s.mentions().stream().filter(x->x.decision().equals("approved")).sorted(Comparator.comparingInt(Mention::start)).toList()) {
                require(m.start()>=last,"approved mention overlap");last=m.end();
            }
        }
        var evs=index(b.evidence(),Evidence::id);
        for(Context c:b.contexts()) {
            var a=b.activities().stream().filter(x->x.id().equals(c.eventId())&&x.version().equals(c.eventVersion())).findFirst().orElseThrow();
            var roleRelations=b.relations().stream().filter(r->c.relationIds().contains(r.id())&&r.decision().equals("approved")
                    &&PERSON_ROLES.contains(r.type())&&(r.objectId().equals(a.id())||r.objectId().equals(a.billId()))).toList();
            Set<String> actors=new HashSet<>(); roleRelations.forEach(r->actors.add(r.subjectId()));
            require(actors.equals(new HashSet<>(a.personIds())),"activity participant roles are not approved or missing");
            for(var ae:a.evidence()) {
                Evidence e=evs.get(ae.id());require(usable(b,e),"activity evidence unavailable or restricted");
                Document d=b.documents().stream().filter(x->x.id().equals(e.documentId())&&x.version().equals(e.documentVersion())&&x.extractionVersion().equals(e.extractionVersion())).findFirst().orElseThrow();
                Segment s=d.segments().stream().filter(x->x.id().equals(e.segmentId())).findFirst().orElseThrow();
                require(ae.sourceUrl().equals(d.sourceUrl())&&ae.sourceVersion().equals(d.version())&&slice(s.text(),e.start(),e.end()).equals(ae.excerpt()),"activity evidence does not match its fixed source span");
            }
            c.evidenceIds().forEach(id->require(usable(b,evs.get(id)),"public context evidence unavailable or restricted"));
            b.relations().stream().filter(r->c.relationIds().contains(r.id())&&r.decision().equals("approved"))
                    .forEach(r->r.evidenceIds().forEach(id->require(usable(b,evs.get(id)),"public relation evidence unavailable or restricted")));
        }
        b.relations().stream().filter(r->r.decision().equals("approved"))
                .forEach(r->r.evidenceIds().forEach(id->require(usable(b,evs.get(id)),"public relation evidence unavailable or restricted")));
        for(Entity entity:b.entities()) {
            for(Fact fact:entity.facts())for(String id:fact.evidenceIds()) {
                require(usable(b,evs.get(id)),"public fact evidence unavailable or restricted");
                if(entity.kind().equals("person"))require(reviewedIdentity(b,entity.id(),evs.get(id)),"public fact identity is not approved for its evidence span");
            }
            for(Tenure tenure:entity.tenures())for(String id:tenure.evidenceIds()) {
                require(usable(b,evs.get(id)),"public tenure evidence unavailable or restricted");
                require(reviewedIdentity(b,entity.id(),evs.get(id)),"public tenure identity is not approved for its evidence span");
            }
            if(entity.kind().equals("person")) {
                boolean unchangedLegacy=verifiedExistingPeople.contains(entity.id())&&entity.facts().isEmpty()&&entity.tenures().isEmpty()&&b.documents().isEmpty();
                require(unchangedLegacy||b.evidence().stream().anyMatch(e->reviewedIdentity(b,entity.id(),e)),"public person identity evidence is not approved or usable");
            }
        }
    }
    /** Identity approval is bound to the same immutable source coordinates as the claim. */
    static boolean reviewedIdentity(KnowledgeBatch b,String personId,Evidence e) {
        return usable(b,e)&&b.documents().stream().filter(d->sameDocument(e,d))
                .flatMap(d->d.segments().stream()).filter(s->s.id().equals(e.segmentId()))
                .flatMap(s->s.mentions().stream()).anyMatch(m->m.decision().equals("approved")&&personId.equals(m.personId())
                        &&m.start()>=e.start()&&m.end()<=e.end());
    }
    static boolean reviewedPersonDocument(KnowledgeBatch b,String personId,Document d) {
        return b.evidence().stream().anyMatch(e->sameDocument(e,d)&&reviewedIdentity(b,personId,e));
    }
    private static boolean sameDocument(Evidence e,Document d) {
        return e.documentId().equals(d.id())&&e.documentVersion().equals(d.version())&&e.extractionVersion().equals(d.extractionVersion());
    }
    public static boolean usable(KnowledgeBatch b,Evidence e) {
        return e!=null&&b.documents().stream().anyMatch(d->d.id().equals(e.documentId())&&d.version().equals(e.documentVersion())
                &&d.extractionVersion().equals(e.extractionVersion())&&d.licenseStatus().equals("allowed")&&Set.of("available","partial").contains(d.bodyStatus()));
    }
    public static String slice(String text,int start,int end) {
        require(text!=null&&start>=0&&end>start&&end<=text.codePointCount(0,text.length()),"invalid code point range");
        return text.substring(text.offsetByCodePoints(0,start),text.offsetByCodePoints(0,end));
    }
    public static void require(boolean condition,String message) { if(!condition)throw new IllegalArgumentException(message); }
    private static void decision(String d) { require(d!=null&&DECISIONS.contains(d),"unsupported decision"); }
    private static void person(Map<String,Entity> m,String id) { require(kind(m,id,"person"),"person entity unavailable"); }
    private static boolean kind(Map<String,Entity> m,String id,String kind) { return m.containsKey(id)&&m.get(id).kind().equals(kind); }
    private static void text(String s,int max,String field) { require(s!=null&&!s.isBlank()&&s.length()<=max&&s.indexOf('\0')<0,"invalid "+field); }
    private static void bounded(List<?> list,int max,String field) { require(list!=null&&list.size()<=max,"invalid "+field); }
    private static void refs(List<String> ids,Map<String,?> index,String field) { bounded(ids,1000,field); require(!ids.isEmpty(),field+" required"); ids.forEach(id->require(index.containsKey(id),field+" unavailable")); }
    private static <T> Map<String,T> index(List<T> values,java.util.function.Function<T,String> id) {
        Map<String,T> map=new LinkedHashMap<>(); for(T v:values)require(v!=null&&id.apply(v)!=null&&map.putIfAbsent(id.apply(v),v)==null,"duplicate or missing identifier");return map;
    }
}
