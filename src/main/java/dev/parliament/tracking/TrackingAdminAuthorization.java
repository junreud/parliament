package dev.parliament.tracking;

import org.springframework.http.HttpStatus;
import org.springframework.web.server.ResponseStatusException;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;

public final class TrackingAdminAuthorization {
    private final byte[] expected;

    public TrackingAdminAuthorization(String secret) {
        if (secret == null || secret.isBlank())
            throw new IllegalStateException("tracking.admin-key is required");
        expected = secret.getBytes(StandardCharsets.UTF_8);
    }

    public void authorize(String supplied) {
        if (!MessageDigest.isEqual(
                expected,
                supplied == null ? new byte[0] : supplied.getBytes(StandardCharsets.UTF_8))) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN, "invalid admin key");
        }
    }
}
