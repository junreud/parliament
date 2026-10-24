package dev.parliament.knowledge;

import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.time.Instant;
import java.util.List;
import org.springframework.http.HttpStatus;
import org.springframework.r2dbc.core.DatabaseClient;
import org.springframework.web.server.ResponseStatusException;
import reactor.core.publisher.Mono;

/** Fail explicitly rather than return an apparently complete graph with missing newer decisions. */
final class KnowledgeGraphLimits {
    static final int REVISIONS=512;
    static final int BYTES=16*1024*1024;
    static final int PEOPLE_SCANNED=5000;
    static final Duration DURATION=Duration.ofSeconds(10);
    private record Payload(String value,Instant reviewedAt) {}
    static Mono<List<KnowledgeGraphProfiles.Revision>> read(DatabaseClient.GenericExecuteSpec query,KnowledgeJson json) {
        return Mono.defer(()->{
            long[] count={0,0};
            return query.map((r,m)->new Payload(r.get("payload",String.class),r.get("reviewed_at",Instant.class))).all()
                    .<KnowledgeGraphProfiles.Revision>handle((payload,sink)->{
                        count[0]++;
                        if(payload.value().length()>BYTES) {sink.error(exceeded());return;}
                        int bytes=payload.value().getBytes(StandardCharsets.UTF_8).length;
                        count[1]+=bytes;
                        if(count[0]>REVISIONS||count[1]>BYTES) {sink.error(exceeded());return;}
                        sink.next(new KnowledgeGraphProfiles.Revision(json.read(payload.value(),KnowledgeBatch.class),payload.reviewedAt(),bytes));
                    }).collectList();
        });
    }
    static <T> Mono<T> timed(Mono<T> query) {return query.timeout(DURATION,Mono.error(exceeded()));}
    static long deadline() {return System.nanoTime()+DURATION.toNanos();}
    static void checkTime(long deadline) {if(System.nanoTime()>deadline)throw exceeded();}
    static ResponseStatusException exceeded() {return new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE,"knowledge query scope exceeds the bounded read budget; narrow the search or graph root");}
}
