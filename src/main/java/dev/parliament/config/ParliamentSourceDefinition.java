package dev.parliament.config;

import java.util.Map;

public record ParliamentSourceDefinition(
        String key,
        String apiCode,
        String name,
        String dataGoKrId,
        ParliamentMediaType mediaType,
        ParliamentCollectionMode collectionMode,
        Map<String, String> fixedParams
) {
    public ParliamentSourceDefinition {
        fixedParams = fixedParams == null ? Map.of() : Map.copyOf(fixedParams);
    }
}

