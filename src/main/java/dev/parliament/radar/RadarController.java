package dev.parliament.radar;

import com.fasterxml.jackson.databind.JsonNode;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;
import reactor.core.publisher.Mono;
import reactor.core.scheduler.Schedulers;
import java.util.Map;

/** Bounded read-only projection; request parameters never select files or trigger collection. */
@RestController
public class RadarController {
    private final RadarFeed feed;
    public RadarController(RadarFeed feed) { this.feed=feed; }

    @GetMapping("/api/v1/radar")
    public Mono<ResponseEntity<?>> read() {
        return Mono.<ResponseEntity<?>>fromCallable(() -> ResponseEntity.ok()
            .header("Cache-Control","no-store").header("X-Content-Type-Options","nosniff")
            .body((JsonNode)feed.read()))
            .subscribeOn(Schedulers.boundedElastic())
            .onErrorReturn(ResponseEntity.status(503).header("Cache-Control","no-store")
                .body(Map.of("message","뉴스 수집 자료를 불러오지 못했습니다.")));
    }
}
