package dev.parliament.knowledge;

import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.web.bind.annotation.*;
import reactor.core.publisher.Mono;
import java.util.Map;

@RestController
@RequestMapping("/api/v1")
@ConditionalOnProperty(prefix="knowledge",name="enabled",havingValue="true")
public final class KnowledgeController {
    private final KnowledgeReads reads;
    private final KnowledgeGraphReads graphs;
    public KnowledgeController(KnowledgeReads reads) { this(reads,null); }
    @org.springframework.beans.factory.annotation.Autowired
    public KnowledgeController(KnowledgeReads reads,KnowledgeGraphReads graphs) { this.reads=reads;this.graphs=graphs; }
    @GetMapping("/people/{id}/profile") public Mono<KnowledgeReads.Profile> profile(@PathVariable String id) {return reads.profile(id);}
    @GetMapping("/people/{id}/timeline") public Mono<KnowledgeReads.Timeline> personTimeline(@PathVariable String id,
            @RequestParam(required=false)String cursor,@RequestParam(defaultValue="20")int limit,
            @RequestParam(defaultValue="newest")String order,@RequestParam(required=false)String from,
            @RequestParam(required=false)String until,@RequestParam(required=false)String role) {
        return reads.personTimeline(id,cursor,limit,order,from,until,role);
    }
    @GetMapping("/activities/{id}/context") public Mono<KnowledgeReads.PublicContext> context(@PathVariable String id,@RequestParam(required=false)String version) {return reads.context(id,version);}
    @GetMapping("/documents/{id}") public Mono<Map<String,Object>> document(@PathVariable String id,@RequestParam(required=false)String version,@RequestParam(required=false)String extractionVersion) {return reads.document(id,version,extractionVersion);}
    @GetMapping("/evidence/{id}") public Mono<KnowledgeReads.PublicEvidence> evidence(@PathVariable String id) {return reads.evidence(id);}
    @GetMapping("/bills/{id}/lineage") public Mono<KnowledgeReads.Lineage> lineage(@PathVariable String id) {return reads.lineage(id);}
    @GetMapping("/issues/{id}/timeline") public Mono<KnowledgeReads.Timeline> timeline(@PathVariable String id,@RequestParam(required=false)String cursor,@RequestParam(defaultValue="20")int limit) {return reads.timeline(id,cursor,limit);}
    @GetMapping("/knowledge/graph") public Mono<KnowledgeGraph> graph(@RequestParam String rootId,@RequestParam String rootKind,
            @RequestParam(defaultValue="1")int depth,@RequestParam(defaultValue="40")int limit,@RequestParam(required=false)String relationType) {
        return graphs.graph(rootId,rootKind,depth,limit,relationType);
    }
    @GetMapping("/knowledge/people") public Mono<KnowledgeGraph.People> people(@RequestParam(required=false)String cursor,
            @RequestParam(required=false)String query,@RequestParam(required=false)String organizationId,@RequestParam(defaultValue="40")int limit) {
        return graphs.people(cursor,query,organizationId,limit);
    }
    @ExceptionHandler(IllegalArgumentException.class) @ResponseStatus(org.springframework.http.HttpStatus.BAD_REQUEST)
    public Map<String,String> invalid(IllegalArgumentException e) { return Map.of("error",e.getMessage()==null?"invalid request":e.getMessage()); }
}
