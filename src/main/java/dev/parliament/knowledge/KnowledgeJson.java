package dev.parliament.knowledge;

import com.fasterxml.jackson.databind.*;
import com.fasterxml.jackson.databind.node.*;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.*;

final class KnowledgeJson {
    private final ObjectMapper mapper;
    KnowledgeJson(ObjectMapper mapper) { this.mapper=mapper.copy().disable(SerializationFeature.WRITE_DATES_AS_TIMESTAMPS); }
    String write(Object value) {
        try { return mapper.writeValueAsString(value); }
        catch(Exception e) { throw new IllegalArgumentException("cannot encode knowledge record",e); }
    }
    <T> T read(String value,Class<T> type) {
        try { return mapper.readValue(value,type); }
        catch(Exception e) { throw new IllegalStateException("invalid persisted knowledge record",e); }
    }
    JsonNode tree(Object value) { return mapper.valueToTree(value); }
    @SuppressWarnings("unchecked") Map<String,Object> map(Object value) { return mapper.convertValue(value,Map.class); }
    String canonical(Object value,Set<String> omitted) { return write(clean(tree(value),omitted)); }
    private JsonNode clean(JsonNode node,Set<String> omitted) {
        if(node.isObject()) {
            ObjectNode out=mapper.createObjectNode();
            List<String> names=new ArrayList<>();node.fieldNames().forEachRemaining(names::add);Collections.sort(names);
            for(String name:names)if(!omitted.contains(name))out.set(name,clean(node.get(name),omitted));return out;
        }
        if(node.isArray()) { ArrayNode out=mapper.createArrayNode();node.forEach(x->out.add(clean(x,omitted)));return out; }
        return node;
    }
    static String hash(String value) {
        try { return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8))); }
        catch(java.security.NoSuchAlgorithmException e) { throw new IllegalStateException(e); }
    }
}
