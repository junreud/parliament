package dev.parliament.knowledge;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.r2dbc.core.DatabaseClient;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;
import reactor.core.publisher.Mono;

@RestController
@ConditionalOnProperty(prefix = "knowledge", name = "enabled", havingValue = "true")
public final class PublicLawController {
    private final PublicLaws laws;
    public PublicLawController(DatabaseClient db, ObjectMapper mapper) { laws = new PublicLaws(db, mapper); }
    @GetMapping("/api/v1/laws")
    public Mono<PublicLaws.Page> list() { return laws.list(); }
}
