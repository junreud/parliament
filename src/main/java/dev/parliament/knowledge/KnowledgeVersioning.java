package dev.parliament.knowledge;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import dev.parliament.tracking.Activity;
import java.util.*;
import static dev.parliament.knowledge.KnowledgeBatch.*;

final class KnowledgeVersioning {
    static final Set<String> OBSERVATIONS=Set.of("observationId","collectedAt","observedAt","reviewedAt","rawStorageKey","corrected","changedAt");
    private final KnowledgeJson json;
    KnowledgeVersioning(ObjectMapper mapper) { json=new KnowledgeJson(mapper); }
    String content(KnowledgeBatch b) { return json.canonical(b,OBSERVATIONS); }
    KnowledgeBatch prepare(KnowledgeBatch b) {
        List<Activity> activities=new ArrayList<>();List<Context> contexts=new ArrayList<>();
        for(Activity a:b.activities()) {
            Context c=b.contexts().stream().filter(x->x.eventId().equals(a.id())&&x.eventVersion().equals(a.version())).findFirst().orElseThrow();
            List<Activity.Evidence> grounded=c.evidenceIds().stream().map(id->{
                Evidence e=b.evidence().stream().filter(x->x.id().equals(id)).findFirst().orElseThrow();
                Document d=b.documents().stream().filter(x->x.id().equals(e.documentId())&&x.version().equals(e.documentVersion())&&x.extractionVersion().equals(e.extractionVersion())).findFirst().orElseThrow();
                Segment s=d.segments().stream().filter(x->x.id().equals(e.segmentId())).findFirst().orElseThrow();
                return new Activity.Evidence(e.id(),d.sourceUrl(),KnowledgePolicy.slice(s.text(),e.start(),e.end()),s.locator()+"; codepoints="+e.start()+".."+e.end(),d.version());
            }).toList();
            String sourceUrl=grounded.get(0).sourceUrl();
            Activity safe=new Activity(a.id(),a.type(),a.title(),a.summary(),a.stage(),a.personIds(),a.topics(),a.billId(),a.occurredAt(),a.publishedAt(),a.collectedAt(),sourceUrl,grounded,a.votes(),a.coverage(),false,a.version());
            ObjectNode factual=(ObjectNode)json.tree(safe);factual.remove(List.of("version","corrected","changedAt","collectedAt"));
            Map<String,Object> contract=new TreeMap<>();contract.put("mapper","knowledge-activity-v1");contract.put("activity",factual);
            contract.put("context",Map.of("issueId",b.issueId(),"changeKind",c.changeKind(),
                    "relationIds",c.relationIds(),"evidenceIds",c.evidenceIds(),"documentIds",c.documentIds()));
            contract.put("schedule",Arrays.asList(c.scheduledAt(),c.scheduledPrecision()));
            contract.put("relations",b.relations().stream().filter(r->c.relationIds().contains(r.id())).sorted(Comparator.comparing(Relation::id)).toList());
            contract.put("evidence",b.evidence().stream().filter(e->c.evidenceIds().contains(e.id())||b.relations().stream().anyMatch(r->c.relationIds().contains(r.id())&&r.evidenceIds().contains(e.id()))).sorted(Comparator.comparing(Evidence::id)).toList());
            contract.put("documents",b.documents().stream().filter(d->c.documentIds().contains(d.id())).sorted(Comparator.comparing(Document::id).thenComparing(Document::version)).toList());
            contract.put("entities",b.entities().stream().sorted(Comparator.comparing(Entity::id)).toList());
            contract.put("roleObservations",b.entities().stream().sorted(Comparator.comparing(Entity::id))
                    .flatMap(e->e.tenures().stream().map(t->Map.of("personId",e.id(),"organizationId",t.organizationId(),"roleObservedAt",t.observedAt())))
                    .toList());
            String version="v_"+KnowledgeJson.hash(json.canonical(contract,OBSERVATIONS));
            activities.add(new Activity(a.id(),a.type(),a.title(),a.summary(),a.stage(),a.personIds(),a.topics(),a.billId(),a.occurredAt(),a.publishedAt(),a.collectedAt(),sourceUrl,grounded,a.votes(),a.coverage(),false,version));
            contexts.add(new Context(c.eventId(),version,c.relationIds(),c.evidenceIds(),c.documentIds(),c.changeKind(),c.scheduledAt(),c.scheduledPrecision()));
        }
        return new KnowledgeBatch(b.id(),b.issueId(),b.entities(),b.documents(),b.evidence(),b.relations(),activities,contexts);
    }
}
