package dev.parliament.radar;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.test.web.reactive.server.WebTestClient;
import java.nio.file.Files;
import java.nio.file.Path;
import static org.assertj.core.api.Assertions.*;

class RadarFeedTest {
    @TempDir Path dir;
    private final ObjectMapper mapper = new ObjectMapper();
    private final String empty = """
      {"schemaVersion":1,"date":"2026-10-17","generatedAt":"2026-10-17T08:00:00Z",
       "lastAttemptAt":"2026-10-17T08:00:00Z","status":"ok","runId":"test",
       "selectionMethod":"rules-shortlist-human-review","baselineAvailable":false,
       "items":[],"sources":[],"shortfall":10,"notice":"news candidates"}
      """;

    @Test void missingAndMalformedAreUnavailableRatherThanEmptySuccess() throws Exception {
        Path path = dir.resolve("public.json");
        WebTestClient client = WebTestClient.bindToController(new RadarController(new RadarFeed(path, mapper))).build();
        client.get().uri("/api/v1/radar").exchange().expectStatus().isEqualTo(503);
        Files.writeString(path, "{bad");
        client.get().uri("/api/v1/radar").exchange().expectStatus().isEqualTo(503);
        Files.writeString(path, empty);
        client.get().uri("/api/v1/radar").exchange().expectStatus().isOk()
            .expectHeader().valueEquals("Cache-Control","no-store")
            .expectBody().jsonPath("$.items.length()").isEqualTo(0);
    }

    @Test void neverExposePrivateEditorialFieldsOrServeOversizeFile() throws Exception {
        Path path = dir.resolve("public.json");
        Files.writeString(path,empty.replace("\"items\":[]", "\"privateDraft\":\"hidden\",\"items\":[]"));
        RadarFeed feed = new RadarFeed(path, mapper);
        assertThat(feed.read().has("privateDraft")).isFalse();
        Files.writeString(path," ".repeat(300_000));
        assertThatThrownBy(feed::read).isInstanceOf(Exception.class);
    }

    @Test void rejectUnboundedItemsAndArbitrarySourceLinks() throws Exception {
        Path path = dir.resolve("public.json");
        Files.writeString(path,empty.replace("\"items\":[]", "\"items\":[{\"id\":\"news_123\",\"title\":\"x\",\"articles\":[{\"url\":\"https://evil.example/\"}]}]"));
        assertThatThrownBy(new RadarFeed(path,mapper)::read).isInstanceOf(Exception.class);
    }
    @Test void sourceProjectionDoesNotExposeNestedPrivateDrafts() throws Exception {
        Path path=dir.resolve("public.json");
        Files.writeString(path,empty.replace("\"sources\":[]", "\"sources\":[{\"name\":\"test\",\"privateDraft\":\"secret\"}]"));
        assertThat(new RadarFeed(path,mapper).read().path("sources").get(0).has("privateDraft")).isFalse();
    }
}
