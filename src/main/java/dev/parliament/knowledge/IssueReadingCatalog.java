package dev.parliament.knowledge;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.io.IOException;
import java.security.MessageDigest;
import java.time.Instant;
import java.time.LocalDate;
import java.util.*;
import org.springframework.core.io.Resource;
import org.springframework.http.HttpStatus;
import org.springframework.web.server.ResponseStatusException;

/** Publication coordinates only; editorial text remains in its single source file. */
public final class IssueReadingCatalog {
    public record EvidencePin(String id, String documentId, String documentVersion,
            String extractionVersion, String segmentId, int start, int end) {}
    public record ContextPin(String eventId, String eventVersion) {}
    public record PersonPin(String id, List<String> evidenceIds) {}
    public record BlockPin(String id, String section, int index, List<String> evidenceIds,
            List<String> personIds) {}
    public record Publication(String issueId, String editorialId, String editorialVersion,
            String version, String state, String reviewedAt, String publishedAt,
            List<String> summaryEvidenceIds, List<String> stageEvidenceIds, List<BlockPin> blocks,
            List<ContextPin> contexts, List<PersonPin> people, List<EvidencePin> evidence) {}
    record Prepared(Publication publication, JsonNode editorial, List<IssueReadingReads.Block> blocks) {}
    private record Catalog(List<Publication> publications) {}
    private static final Map<String, String> SECTIONS = Map.of("background", "background", "facts", "fact",
            "claims", "claim", "unknowns", "unknown", "timeline", "event");
    private final ObjectMapper mapper;
    private final Resource source;
    private final Resource catalog;

    public IssueReadingCatalog(ObjectMapper mapper, Resource catalog, Resource source) {
        this.mapper = mapper;
        this.source = source;
        this.catalog = catalog;
        try {
            publications();
        } catch (IOException e) {
            throw new IllegalStateException("issue reading catalog unavailable", e);
        }
    }

    private Map<String, Publication> publications() throws IOException {
        var entries = mapper.treeToValue(read(catalog), Catalog.class).publications();
        if (entries == null || entries.size() > 1000) throw new IOException("invalid catalog");
        var index = new HashMap<String, Publication>();
        for (var entry : entries) {
            if (entry.issueId() == null || index.putIfAbsent(entry.issueId(), entry) != null)
                throw new IOException("duplicate issue mapping");
        }
        return Map.copyOf(index);
    }

    Prepared find(String id) {
        if (id == null || !id.matches("[a-zA-Z0-9_-]{1,128}"))
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST);
        try {
            // Re-read publication state before each request; never retain a withdrawn success.
            var p = publications().get(id);
            if (p == null || !"published".equals(p.state())) throw missing();
            JsonNode editorial = null;
            var issues = read(source).path("issues");
            check(issues.isArray());
            for (var item : issues) {
                if (p.editorialId().equals(item.path("id").asText())) {
                    check(editorial == null);
                    editorial = item;
                }
            }
            if (editorial == null || !"reviewed".equals(editorial.path("reviewStatus").asText())) throw missing();
            check(Objects.equals(p.version(), publicationVersion(p)));
            check(p.editorialVersion().equals(hash(editorial)));
            var reviewed = Instant.parse(p.reviewedAt());
            check(reviewed.equals(Instant.parse(editorial.path("reviewedAt").asText())));
            var published = Instant.parse(p.publishedAt());
            check(!reviewed.isAfter(published) && !published.isAfter(Instant.now()));
            String checked = editorial.path("checkedAt").asText();
            try { LocalDate.parse(checked); } catch (RuntimeException e) { Instant.parse(checked); }
            for (String field : List.of("title", "summary", "currentStage", "nextTrigger"))
                check(editorial.path(field).isTextual() && !editorial.path(field).asText().isBlank());
            check(p.version() != null && p.version().matches("[a-zA-Z0-9_-]{1,128}"));
            check(p.contexts() != null && !p.contexts().isEmpty() && p.contexts().size() <= 20);
            check(p.people() != null && !p.people().isEmpty() && p.people().size() <= 10);
            check(p.evidence() != null && !p.evidence().isEmpty() && p.evidence().size() <= 50);
            check(p.summaryEvidenceIds() != null && !p.summaryEvidenceIds().isEmpty());
            check(p.stageEvidenceIds() != null && !p.stageEvidenceIds().isEmpty());
            check(p.blocks() != null && p.blocks().size() <= 200);
            return new Prepared(p, editorial, blocks(p, editorial));
        } catch (ResponseStatusException e) {
            throw e;
        } catch (IOException e) {
            throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE);
        } catch (RuntimeException e) {
            throw conflict();
        }
    }

    private List<IssueReadingReads.Block> blocks(Publication p, JsonNode editorial) {
        var pins = new HashMap<String, BlockPin>();
        var ids = new HashSet<String>();
        for (var b : p.blocks()) {
            check(b.id() != null && b.id().matches("[a-zA-Z0-9_-]{1,128}") && ids.add(b.id()));
            check(SECTIONS.containsKey(b.section()) && b.index() >= 0);
            check(b.evidenceIds() != null && b.personIds() != null);
            check(b.section().equals("unknowns") || !b.evidenceIds().isEmpty());
            check(pins.putIfAbsent(b.section() + ":" + b.index(), b) == null);
        }
        var result = new ArrayList<IssueReadingReads.Block>();
        for (String section : List.of("background", "facts", "claims", "unknowns", "timeline")) {
            var list = editorial.path(section);
            check(list.isArray());
            for (int i = 0; i < list.size(); i++) {
                var pin = pins.remove(section + ":" + i);
                check(pin != null);
                var node = list.get(i);
                String text = section.equals("timeline") ? node.path("detail").asText() : node.asText();
                check(!text.isBlank());
                String date = null;
                String title = null;
                if (section.equals("timeline")) {
                    date = node.path("date").asText();
                    LocalDate.parse(date);
                    title = node.path("title").asText();
                    check(!title.isBlank());
                } else check(node.isTextual());
                result.add(new IssueReadingReads.Block(pin.id(), SECTIONS.get(section), text, date, title,
                        pin.evidenceIds(), pin.personIds()));
            }
        }
        check(pins.isEmpty());
        check(editorial.path("updates").isArray());
        for (var update : editorial.path("updates")) {
            LocalDate.parse(update.path("date").asText());
            check(update.path("note").isTextual());
        }
        return List.copyOf(result);
    }

    private JsonNode read(Resource resource) throws IOException {
        // Configuration may reference a local file or packaged resource, never a remote URL.
        if (resource instanceof org.springframework.core.io.UrlResource) {
            String protocol = resource.getURL().getProtocol();
            if (!Set.of("file", "jar").contains(protocol)) throw new IOException("remote source forbidden");
            if (protocol.equals("jar") && !resource.getURL().toString().startsWith("jar:file:"))
                throw new IOException("remote jar forbidden");
        }
        try (var stream = resource.getInputStream()) {
            byte[] bytes = stream.readNBytes(2_000_001);
            if (bytes.length > 2_000_000) throw new IOException("resource limit");
            return mapper.readTree(bytes);
        }
    }

    String hash(JsonNode node) throws IOException {
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(mapper.writeValueAsBytes(node)));
        } catch (java.security.NoSuchAlgorithmException e) { throw new IllegalStateException(e); }
    }

    String publicationVersion(Publication publication) throws IOException {
        var projection = (com.fasterxml.jackson.databind.node.ObjectNode) mapper.valueToTree(publication);
        projection.remove(List.of("version", "state"));
        return "reading_" + hash(projection);
    }

    static void check(boolean condition) { if (!condition) throw conflict(); }
    static ResponseStatusException missing() { return new ResponseStatusException(HttpStatus.NOT_FOUND); }
    static ResponseStatusException conflict() { return new ResponseStatusException(HttpStatus.CONFLICT); }
}
