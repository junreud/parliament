package dev.parliament.radar;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import java.io.IOException;
import java.net.URI;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import java.time.LocalDate;
import java.util.List;
import java.util.Map;
import java.util.Set;

/** Fixed-file public news metadata, isolated from private editorial recommendations. */
@Component
public class RadarFeed {
    private static final Map<String, Set<String>> PUBLISHERS = Map.of(
        "연합뉴스", Set.of("www.yna.co.kr","yna.co.kr"), "동아일보", Set.of("www.donga.com"),
        "한겨레", Set.of("www.hani.co.kr"), "경향신문", Set.of("www.khan.co.kr"));
    private final Path path;
    private final ObjectMapper mapper;

    @Autowired
    public RadarFeed(@Value("${radar.feed-path:${RADAR_FEED_PATH:.local/radar/public.json}}") String path, ObjectMapper mapper) {
        this(Path.of(path), mapper);
    }
    public RadarFeed(Path path, ObjectMapper mapper) { this.path=path; this.mapper=mapper; }

    public ObjectNode read() throws IOException {
        byte[] bytes;
        try (var input = Files.newInputStream(path)) {
            bytes=input.readNBytes(262145);
        }
        if (bytes.length>262144) throw new IOException("oversize feed");
        JsonNode raw=mapper.readTree(bytes);
        try {
            require(raw.isObject() && raw.path("schemaVersion").asInt()==1);
            LocalDate.parse(text(raw,"date",10));
            Instant.parse(text(raw,"generatedAt",40));
            Instant.parse(text(raw,"lastAttemptAt",40));
            require(Set.of("ok","partial","unavailable").contains(text(raw,"status",20)));
            require(raw.path("selectionMethod").asText().equals("rules-shortlist-human-review"));
            require(raw.path("baselineAvailable").isBoolean());
            require(raw.path("items").isArray() && raw.path("items").size()<=10);
            require(raw.path("sources").isArray() && raw.path("sources").size()<=8);
            ObjectNode result=mapper.createObjectNode();
            for (String field: List.of("schemaVersion","date","generatedAt","lastAttemptAt","status","selectionMethod","baselineAvailable","runId","shortfall","notice")) {
                if(raw.has(field)) result.set(field,raw.get(field));
            }
            var sources=result.putArray("sources");
            for(JsonNode source:raw.path("sources")) sources.add(project(source,List.of("name","url","kind","status","items","note","error")));
            var items=result.putArray("items");
            for(JsonNode item:raw.path("items")) {
                require(text(item,"id",32).matches("news_[a-f0-9]{16}"));
                text(item,"title",300); text(item,"question",300); text(item,"reason",1000);
                Instant.parse(text(item,"publishedAt",40));
                require(item.path("reviewStatus").asText().equals("unreviewed"));
                require(item.path("evidence").isArray() && item.path("evidence").isEmpty());
                require(item.path("articles").isArray() && !item.path("articles").isEmpty() && item.path("articles").size()<=5);
                for(JsonNode a:item.path("articles")) {
                    text(a,"title",300);
                    URI uri=URI.create(text(a,"url",2048));
                    require("https".equals(uri.getScheme()) && uri.getUserInfo()==null && (uri.getPort()==-1 || uri.getPort()==443));
                    require(PUBLISHERS.getOrDefault(text(a,"publisher",30),Set.of()).contains(uri.getHost()));
                    Instant.parse(text(a,"publishedAt",40));
                }
                ObjectNode projected=mapper.createObjectNode();
                for(String field:List.of("id","title","question","reason","score","articleCount","publisherCount","independentSignals","growth","searchSignals","publishedAt","articles","evidence","reviewStatus")) projected.set(field,item.get(field));
                var articles=projected.putArray("articles");
                for(JsonNode article:item.path("articles")) articles.add(project(article,List.of("title","url","publisher","publishedAt")));
                projected.set("growth",project(item.path("growth"),List.of("status","recent","previous")));
                var signals=projected.putArray("searchSignals");
                for(JsonNode signal:item.path("searchSignals")) signals.add(project(signal,List.of("keyword","traffic","publishedAt")));
                items.add(projected);
            }
            return result;
        } catch(RuntimeException error) { throw new IOException("invalid news feed",error); }
    }
    private ObjectNode project(JsonNode node,List<String> fields) {
        ObjectNode result=mapper.createObjectNode();
        for(String field:fields) if(node.has(field)) result.set(field,node.get(field));
        return result;
    }
    private static String text(JsonNode node,String key,int max) {
        JsonNode value=node.path(key);
        require(value.isTextual() && !value.asText().isBlank() && value.asText().length()<=max);
        return value.asText();
    }
    private static void require(boolean valid) { if(!valid) throw new IllegalArgumentException("invalid feed field"); }
}
