package dev.parliament.knowledge;

import java.time.Instant;
import java.util.*;
import static dev.parliament.knowledge.KnowledgeBatch.*;
import static dev.parliament.knowledge.KnowledgeGraphProfiles.*;

/** Projects reviewed facts into a typed graph without interpreting a name mention as an action. */
final class KnowledgeGraphProjection {
    static final Set<String> KINDS=Set.of("person","organization","bill","policy","activity","document","issue");
    static final Set<String> TYPES=Set.of("lead_sponsor","co_sponsor","speaker","voter","scheduled_participant",
            "publisher","implementing_agency","committee_proposer","incorporated_into_alternative","concerns","records",
            "holds_office","supported_by","in_issue");
    record Data(Map<String,KnowledgeGraph.Node> nodes,List<KnowledgeGraph.Edge> edges) {}

    static Data build(List<Revision> revisions,Set<String> publishedEvents,boolean candidate) {
        return build(revisions,publishedEvents,candidate,KnowledgeGraphLimits.deadline());
    }
    static Data build(List<Revision> revisions,Set<String> publishedEvents,boolean candidate,long deadline) {
        List<Revision> ordered=ordered(revisions);
        Map<String,KnowledgeGraph.Node> nodes=new LinkedHashMap<>();
        Map<String,KnowledgeGraph.Edge> edges=new LinkedHashMap<>();
        Map<String,RelationClaim> relations=new LinkedHashMap<>();
        Set<String> entityIds=new LinkedHashSet<>();
        for(Revision revision:ordered) {
            KnowledgeGraphLimits.checkTime(deadline);
            var b=revision.batch();
            for(Entity e:b.entities()) {
                entityIds.add(e.id());put(nodes,e.kind(),e.id(),e.name(),href(e.kind(),e.id()),null);
            }
            for(Document d:b.documents())put(nodes,"document",d.id(),d.title(),
                    "/documents/"+d.id()+"?version="+d.version()+"&extractionVersion="+d.extractionVersion(),d.version());
            for(var a:b.activities())if(candidate||publishedEvents.contains(a.id()+":"+a.version())) {
                put(nodes,"activity",a.id(),a.title(),"/activities/"+a.id()+"?version="+a.version(),a.version());
                Context c=b.contexts().stream().filter(x->x.eventId().equals(a.id())&&x.eventVersion().equals(a.version())).findFirst().orElseThrow();
                if(available(b,c.evidenceIds(),candidate)) {
                    put(nodes,"issue",b.issueId(),issueTitle(b.issueId()),"/issues/"+b.issueId(),null);
                    add(edges,"activity:"+a.id(),"issue:"+b.issueId(),"in_issue","관련 이슈",c.evidenceIds(),revision,null,null,null);
                    supports(edges,b,"activity:"+a.id(),c.evidenceIds(),revision,candidate);
                }
            }
            for(Relation r:b.relations())relations.putIfAbsent(r.subjectId()+"|"+r.objectId()+"|"+r.type(),new RelationClaim(r,revision));
        }
        // Select the latest published decision before filtering out pending/rejected edges.
        for(RelationClaim claim:relations.values()) {
            KnowledgeGraphLimits.checkTime(deadline);
            Relation r=claim.relation();var revision=claim.revision();var b=revision.batch();
            if(!candidate&&!r.decision().equals("approved")||!available(b,r.evidenceIds(),candidate))continue;
            String from=relationSource(b,r),to=relationTarget(b,r);
            if(!nodes.containsKey(from)||!nodes.containsKey(to))continue;
            if(from.startsWith("activity:")&&!eventVisible(from,b,publishedEvents,candidate)
                    ||to.startsWith("activity:")&&!eventVisible(to,b,publishedEvents,candidate))continue;
            String label=label(r.type());
            if(candidate&&!r.decision().equals("approved"))label=(r.decision().equals("pending")?"검수 대기: ":"기각: ")+label;
            add(edges,from,to,r.type(),label,r.evidenceIds(),revision,null,null,null);
            supports(edges,b,from,r.evidenceIds(),revision,candidate);
            supports(edges,b,to,r.evidenceIds(),revision,candidate);
        }
        for(String id:entityIds) {
            KnowledgeGraphLimits.checkTime(deadline);
            Snapshot snapshot=candidate?candidateSnapshot(id,ordered):merge(id,ordered,deadline);
            for(FactClaim claim:snapshot.facts()) {
                var b=claim.revision().batch();Entity entity=find(b,id);
                supports(edges,b,entity.kind()+":"+id,claim.fact().evidenceIds(),claim.revision(),candidate);
            }
            for(OfficeClaim claim:snapshot.offices()) {
                var t=claim.tenure();var revision=claim.revision();String from="person:"+id,to="organization:"+t.organizationId();
                if(!nodes.containsKey(to))continue;
                add(edges,from,to,"holds_office",t.position(),t.evidenceIds(),revision,t.validFrom(),t.validUntil(),t.observedAt());
                supports(edges,revision.batch(),from,t.evidenceIds(),revision,candidate);
            }
        }
        return new Data(Map.copyOf(nodes),List.copyOf(edges.values()));
    }
    private record RelationClaim(Relation relation,Revision revision) {}
    private static Snapshot candidateSnapshot(String id,List<Revision> revisions) {
        List<FactClaim> facts=new ArrayList<>();List<OfficeClaim> offices=new ArrayList<>();
        for(Revision r:revisions) {
            Entity e=r.batch().entities().stream().filter(x->x.id().equals(id)).findFirst().orElse(null);
            if(e==null)continue;
            for(Fact f:e.facts())if(available(r.batch(),f.evidenceIds(),true))facts.add(new FactClaim(f,r));
            for(Tenure t:e.tenures())if(available(r.batch(),t.evidenceIds(),true))offices.add(new OfficeClaim(t,r,t.organizationId()));
        }
        return new Snapshot(facts,offices);
    }
    private static boolean eventVisible(String key,KnowledgeBatch b,Set<String> published,boolean candidate) {
        return candidate||b.activities().stream().anyMatch(a->key.equals("activity:"+a.id())&&published.contains(a.id()+":"+a.version()));
    }
    private static String relationSource(KnowledgeBatch b,Relation r) {
        return switch(r.type()) {
            case "records"->"document:"+r.subjectId();
            case "lead_sponsor","co_sponsor","speaker","voter","scheduled_participant"->"person:"+r.subjectId();
            case "publisher","implementing_agency","committee_proposer"->"organization:"+r.subjectId();
            case "incorporated_into_alternative"->"bill:"+r.subjectId();
            default->billOrActivity(b,r.subjectId());
        };
    }
    private static String relationTarget(KnowledgeBatch b,Relation r) {
        return switch(r.type()) {
            case "speaker","voter","scheduled_participant","records"->"activity:"+r.objectId();
            case "incorporated_into_alternative"->"bill:"+r.objectId();
            case "concerns"->"policy:"+r.objectId();
            case "lead_sponsor","co_sponsor"->billOrActivity(b,r.objectId());
            default->b.entities().stream().filter(e->e.id().equals(r.objectId())&&Set.of("bill","policy").contains(e.kind()))
                    .map(e->e.kind()+":"+e.id()).findFirst().orElse("activity:"+r.objectId());
        };
    }
    private static String billOrActivity(KnowledgeBatch b,String id) {
        return b.entities().stream().anyMatch(e->e.id().equals(id)&&e.kind().equals("bill"))?"bill:"+id:"activity:"+id;
    }
    private static Entity find(KnowledgeBatch b,String id) {return b.entities().stream().filter(e->e.id().equals(id)).findFirst().orElseThrow();}
    private static boolean available(KnowledgeBatch b,List<String> refs,boolean candidate) {
        if(!candidate)return usable(b,refs);
        return refs!=null&&!refs.isEmpty()&&refs.stream().allMatch(id->b.evidence().stream().anyMatch(e->e.id().equals(id)&&
                b.documents().stream().anyMatch(d->d.id().equals(e.documentId())&&d.version().equals(e.documentVersion())
                    &&d.extractionVersion().equals(e.extractionVersion())&&Set.of("available","partial").contains(d.bodyStatus()))));
    }
    private static void supports(Map<String,KnowledgeGraph.Edge> edges,KnowledgeBatch b,String source,List<String> refs,Revision revision,boolean candidate) {
        if(source.startsWith("document:")||!available(b,refs,candidate))return;
        Map<String,List<String>> byDocument=new TreeMap<>();
        for(Evidence e:b.evidence())if(refs.contains(e.id()))byDocument.computeIfAbsent(e.documentId(),ignored->new ArrayList<>()).add(e.id());
        byDocument.forEach((id,evidence)->add(edges,source,"document:"+id,"supported_by","공식 원문 근거",evidence,revision,null,null,null));
    }
    private static void add(Map<String,KnowledgeGraph.Edge> edges,String from,String to,String type,String label,List<String> evidence,Revision revision,
            java.time.LocalDate validFrom,java.time.LocalDate validUntil,Instant observedAt) {
        String id="ge_"+KnowledgeJson.hash(from+"|"+to+"|"+type+"|"+label+"|"+String.join(",",evidence.stream().sorted().toList()));
        edges.putIfAbsent(id,new KnowledgeGraph.Edge(id,from,to,type,label,List.copyOf(evidence),revision.batch().id(),revision.reviewedAt(),validFrom,validUntil,observedAt));
    }
    private static void put(Map<String,KnowledgeGraph.Node> nodes,String kind,String id,String label,String href,String version) {
        nodes.putIfAbsent(kind+":"+id,new KnowledgeGraph.Node(kind+":"+id,id,kind,label,href,version));
    }
    private static String href(String kind,String id) {
        return switch(kind) {
            case "person"->"/people/"+id;
            case "bill"->"/bills/"+id;
            default->"/explore?rootKind="+kind+"&rootId="+id;
        };
    }
    private static String issueTitle(String id) {try{return new dev.parliament.tracking.TrackingIssues().find(id).title();}catch(org.springframework.web.server.ResponseStatusException e){return id;}}
    private static String label(String type) {
        return switch(type) {
            case "lead_sponsor"->"대표발의";case "co_sponsor"->"공동발의";case "speaker"->"발언";
            case "voter"->"표결 참여";case "scheduled_participant"->"참여 예정";case "publisher"->"기관 발표";
            case "implementing_agency"->"수행 기관";case "committee_proposer"->"위원회 제안";
            case "incorporated_into_alternative"->"대안에 통합";case "concerns"->"관련 정책";case "records"->"사건 기록";
            default->type;
        };
    }
}
