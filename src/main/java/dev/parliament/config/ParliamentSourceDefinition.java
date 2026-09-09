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

    public ParliamentSourceDefinition withFixedParams(Map<String, String> additionalParams) {
        java.util.LinkedHashMap<String, String> merged = new java.util.LinkedHashMap<>(fixedParams);
        merged.putAll(additionalParams);
        return new ParliamentSourceDefinition(
                key, apiCode, name, dataGoKrId, mediaType, collectionMode, merged);
    }
}
