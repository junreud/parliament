package dev.parliament.tracking;

import com.fasterxml.jackson.databind.ObjectMapper;

import java.util.Base64;

/** Opaque key cursor tied to one verified source contract and projection kind. */
record TrackingProjectionCursor(
        String source, String kind, String record, String bill, String session) {
    private static final ObjectMapper MAPPER = new ObjectMapper();

    String encode() {
        try {
            return Base64.getUrlEncoder()
                    .withoutPadding()
                    .encodeToString(MAPPER.writeValueAsBytes(this));
        } catch (com.fasterxml.jackson.core.JsonProcessingException ex) {
            throw new IllegalStateException(ex);
        }
    }

    static TrackingProjectionCursor decode(String cursor, String source, String kind) {
        try {
            TrackingPolicy.require(
                    cursor != null && cursor.length() <= 2048, "invalid projection cursor");
            var value =
                    MAPPER.readValue(
                            Base64.getUrlDecoder().decode(cursor), TrackingProjectionCursor.class);
            TrackingPolicy.require(
                    source.equals(value.source()) && kind.equals(value.kind()),
                    "projection cursor belongs to another source");
            if (kind.equals("vote")) {
                TrackingPolicy.text(value.bill(), 255, "bill cursor");
                TrackingPolicy.text(value.session(), 512, "session cursor");
            } else TrackingPolicy.text(value.record(), 255, "record cursor");
            return value;
        } catch (java.io.IOException | RuntimeException ex) {
            throw new IllegalArgumentException("invalid projection cursor");
        }
    }
}
