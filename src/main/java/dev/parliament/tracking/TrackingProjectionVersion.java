package dev.parliament.tracking;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;

import java.util.Comparator;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;

/** Versions derived facts independently of their immutable raw-source versions. */
final class TrackingProjectionVersion {
    // Increment these revisions when extraction/normalization behavior changes.
    static final String ROW_REVISION = "assembly-structural-v1";
    static final String VOTE_REVISION = "assembly-vote-session-v1";
    private static final ObjectMapper MAPPER =
            new ObjectMapper()
                    .registerModule(new JavaTimeModule())
                    .disable(SerializationFeature.WRITE_DATES_AS_TIMESTAMPS);

    private TrackingProjectionVersion() {}

    static Activity derive(
            Activity activity,
            String revision,
            TrackingProjection.Contract contract,
            List<String> memberVersions) {
        Activity normalized =
                copy(
                        activity,
                        activity.personIds().stream().distinct().sorted().toList(),
                        activity.topics().stream().distinct().sorted().toList(),
                        activity.evidence().stream()
                                .distinct()
                                .sorted(
                                        Comparator.comparing(
                                                TrackingProjectionVersion::canonicalJson))
                                .toList(),
                        activity.votes().stream()
                                .distinct()
                                .sorted(
                                        Comparator.comparing(
                                                TrackingProjectionVersion::canonicalJson))
                                .toList(),
                        "pending");
        ObjectNode payload = MAPPER.valueToTree(normalized);
        payload.remove(List.of("version", "corrected", "changedAt"));
        ObjectNode fingerprint = MAPPER.createObjectNode();
        fingerprint.put("projectionRevision", revision);
        fingerprint.set("activity", payload);
        if (contract != null) fingerprint.set("contract", effectiveContract(contract));
        fingerprint.set(
                "memberDerivedVersions",
                MAPPER.valueToTree(memberVersions.stream().sorted().toList()));
        String version = "v_" + TrackingRepository.hash(canonicalJson(fingerprint));
        return copy(
                normalized,
                normalized.personIds(),
                normalized.topics(),
                normalized.evidence(),
                normalized.votes(),
                version);
    }

    private static ObjectNode effectiveContract(TrackingProjection.Contract contract) {
        ObjectNode node = MAPPER.createObjectNode();
        node.put("sourceKey", contract.sourceKey());
        node.put("kind", contract.kind());
        node.put("personNamespace", contract.personNamespace());
        node.set("fields", MAPPER.valueToTree(contract.fields()));
        node.set(
                "stageMap",
                MAPPER.valueToTree(contract.stageMap() == null ? Map.of() : contract.stageMap()));
        node.set(
                "voteMap",
                MAPPER.valueToTree(contract.voteMap() == null ? Map.of() : contract.voteMap()));
        // Pagination and verification assertion are operational, not extraction semantics.
        return node;
    }

    private static Activity copy(
            Activity a,
            List<String> people,
            List<String> topics,
            List<Activity.Evidence> evidence,
            List<Activity.Vote> votes,
            String version) {
        return new Activity(
                a.id(),
                a.type(),
                a.title(),
                a.summary(),
                a.stage(),
                people,
                topics,
                a.billId(),
                a.occurredAt(),
                a.publishedAt(),
                a.collectedAt(),
                a.sourceUrl(),
                evidence,
                votes,
                a.coverage(),
                false,
                version,
                null);
    }

    private static String canonicalJson(Object value) {
        JsonNode node = value instanceof JsonNode json ? json : MAPPER.valueToTree(value);
        try {
            return MAPPER.writeValueAsString(canonical(node));
        } catch (JsonProcessingException exception) {
            throw new IllegalArgumentException("invalid derived activity payload", exception);
        }
    }

    private static JsonNode canonical(JsonNode node) {
        if (node.isObject()) {
            TreeMap<String, JsonNode> fields = new TreeMap<>();
            node.fields()
                    .forEachRemaining(
                            entry -> fields.put(entry.getKey(), canonical(entry.getValue())));
            ObjectNode sorted = MAPPER.createObjectNode();
            fields.forEach(sorted::set);
            return sorted;
        }
        if (node.isArray()) {
            var array = MAPPER.createArrayNode();
            node.forEach(value -> array.add(canonical(value)));
            return array;
        }
        return node;
    }
}
