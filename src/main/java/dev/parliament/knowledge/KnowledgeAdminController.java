package dev.parliament.knowledge;

import dev.parliament.tracking.TrackingAdminAuthorization;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.web.bind.annotation.*;
import reactor.core.publisher.Mono;
import java.util.Map;

@RestController
@RequestMapping("/admin/tracking/knowledge/batches")
@ConditionalOnProperty(prefix="knowledge",name="enabled",havingValue="true")
public final class KnowledgeAdminController {
    public record Review(String decision,String reviewer,String reason) {}
    private final KnowledgeRepository repository;
    private final TrackingAdminAuthorization auth;
    private final KnowledgeGraphReads graphs;
    public KnowledgeAdminController(KnowledgeRepository repository,TrackingAdminAuthorization auth) {this(repository,auth,null);}
    @org.springframework.beans.factory.annotation.Autowired
    public KnowledgeAdminController(KnowledgeRepository repository,TrackingAdminAuthorization auth,KnowledgeGraphReads graphs) {this.repository=repository;this.auth=auth;this.graphs=graphs;}
    @PostMapping public Mono<KnowledgeRepository.ImportResult> add(@RequestHeader(name="X-Parliament-Ingestion-Key",required=false)String key,@RequestBody KnowledgeBatch batch) {auth.authorize(key);return repository.importBatch(batch);}
    @GetMapping("/{id}") public Mono<KnowledgeRepository.Saved> get(@RequestHeader(name="X-Parliament-Ingestion-Key",required=false)String key,@PathVariable String id) {auth.authorize(key);return repository.get(id);}
    @PostMapping("/{id}/review") public Mono<KnowledgeRepository.Saved> review(@RequestHeader(name="X-Parliament-Ingestion-Key",required=false)String key,@PathVariable String id,@RequestBody Review review) {auth.authorize(key);return repository.review(id,review.decision(),review.reviewer(),review.reason());}
    @GetMapping("/{id}/graph") public Mono<KnowledgeGraph> graph(@RequestHeader(name="X-Parliament-Ingestion-Key",required=false)String key,@PathVariable String id) {auth.authorize(key);return graphs.candidate(id);}
    @ExceptionHandler(IllegalArgumentException.class) @ResponseStatus(org.springframework.http.HttpStatus.BAD_REQUEST)
    public Map<String,String> invalid(IllegalArgumentException e) {return Map.of("error",e.getMessage()==null?"invalid request":e.getMessage());}
}
