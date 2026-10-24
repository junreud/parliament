package dev.parliament.tracking;

import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.Base64;

public record TrackingCursor(Instant publishedAt, String id) {
    public String encode() {
        return Base64.getUrlEncoder()
                .withoutPadding()
                .encodeToString((publishedAt + "|" + id).getBytes(StandardCharsets.UTF_8));
    }

    public static TrackingCursor decode(String value) {
        try {
            if (value == null || value.length() > 300)
                throw new IllegalArgumentException("invalid cursor");
            String[] parts =
                    new String(Base64.getUrlDecoder().decode(value), StandardCharsets.UTF_8)
                            .split("\\|", -1);
            if (parts.length != 2) throw new IllegalArgumentException("invalid cursor");
            return new TrackingCursor(Instant.parse(parts[0]), TrackingPolicy.id(parts[1]));
        } catch (RuntimeException ex) {
            throw new IllegalArgumentException("invalid cursor");
        }
    }
}
