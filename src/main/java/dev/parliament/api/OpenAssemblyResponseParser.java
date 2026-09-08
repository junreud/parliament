package dev.parliament.api;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

import java.util.List;
import java.util.Map;

public class OpenAssemblyResponseParser {
    private static final String SUCCESS_CODE = "INFO-000";
    private final ObjectMapper objectMapper = new ObjectMapper();

    public OpenAssemblyPage parse(String apiCode, JsonNode body) {
        JsonNode topLevelResult = body.path("RESULT");
        if (!topLevelResult.isMissingNode()) {
            throw apiError(topLevelResult);
        }

        JsonNode sections = body.path(apiCode);
        if (!sections.isArray() || sections.isEmpty()) {
            throw new OpenAssemblyApiException("missing response section for " + apiCode);
        }
        JsonNode head = sections.get(0).path("head");
        if (!head.isArray() || head.size() < 2) {
            throw new OpenAssemblyApiException("missing response head for " + apiCode);
        }
        JsonNode result = head.get(1).path("RESULT");
        if (!SUCCESS_CODE.equals(result.path("CODE").asText())) {
            throw apiError(result);
        }
        int totalCount = head.get(0).path("list_total_count").asInt(0);
        JsonNode rowNode = sections.size() > 1 ? sections.get(1).path("row") : null;
        List<Map<String, Object>> rows = rowNode != null && rowNode.isArray()
                ? objectMapper.convertValue(rowNode, new TypeReference<>() { })
                : List.of();
        return new OpenAssemblyPage(totalCount, List.copyOf(rows));
    }

    private OpenAssemblyApiException apiError(JsonNode result) {
        String code = result.path("CODE").asText("UNKNOWN");
        String message = result.path("MESSAGE").asText("Open Assembly API failed");
        return new OpenAssemblyApiException("Open Assembly API error " + code + ": " + message);
    }
}

