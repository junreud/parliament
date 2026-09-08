package dev.parliament.config;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;

import java.io.IOException;
import java.io.InputStream;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

public class ParliamentSourceCatalog {
    private static final String DEFAULT_RESOURCE = "/parliament/open-assembly-sources.json";

    private final List<ParliamentSourceDefinition> definitions;
    private final Map<String, ParliamentSourceDefinition> byKey;

    private ParliamentSourceCatalog(List<ParliamentSourceDefinition> definitions) {
        LinkedHashMap<String, ParliamentSourceDefinition> unique = new LinkedHashMap<>();
        for (ParliamentSourceDefinition definition : definitions) {
            if (unique.putIfAbsent(definition.key(), definition) != null) {
                throw new IllegalArgumentException("duplicate parliament source key: " + definition.key());
            }
        }
        this.definitions = List.copyOf(unique.values());
        this.byKey = Map.copyOf(unique);
    }

    public static ParliamentSourceCatalog loadDefault(ObjectMapper objectMapper) {
        try (InputStream input = ParliamentSourceCatalog.class.getResourceAsStream(DEFAULT_RESOURCE)) {
            if (input == null) {
                throw new IllegalStateException("missing parliament source catalog: " + DEFAULT_RESOURCE);
            }
            Map<String, Object> root = objectMapper.readValue(input, new TypeReference<>() { });
            List<ParliamentSourceDefinition> definitions = objectMapper.convertValue(
                    root.get("definitions"), new TypeReference<>() { });
            return new ParliamentSourceCatalog(definitions);
        } catch (IOException error) {
            throw new IllegalStateException("failed to load parliament source catalog", error);
        }
    }

    public static ParliamentSourceCatalog of(List<ParliamentSourceDefinition> definitions) {
        return new ParliamentSourceCatalog(definitions);
    }

    public List<ParliamentSourceDefinition> all() {
        return definitions;
    }

    public List<ParliamentSourceDefinition> active() {
        return definitions.stream()
                .filter(source -> source.collectionMode() == ParliamentCollectionMode.PAGE)
                .filter(source -> source.mediaType() != ParliamentMediaType.VIDEO)
                .toList();
    }

    public ParliamentSourceDefinition requireActive(String key) {
        ParliamentSourceDefinition source = byKey.get(key);
        if (source == null
                || source.collectionMode() != ParliamentCollectionMode.PAGE
                || source.mediaType() == ParliamentMediaType.VIDEO) {
            throw new IllegalArgumentException("unknown or excluded parliament source: " + key);
        }
        return source;
    }
}
