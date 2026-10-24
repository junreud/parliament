package dev.parliament.tracking;

import org.springframework.http.HttpStatus;
import org.springframework.web.server.ResponseStatusException;

import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.util.Base64;
import java.util.Locale;

public final class TrackingAuthPolicy {
    private static final SecureRandom RANDOM = new SecureRandom();
    private final String baseUrl;
    private final String origin;
    private final boolean secure;

    public TrackingAuthPolicy(String value) {
        URI uri;
        try {
            uri = URI.create(value);
        } catch (RuntimeException ex) {
            throw new IllegalArgumentException("fixed public-base-url required");
        }
        boolean local =
                uri.getHost() != null
                        && java.util.Set.of("localhost", "127.0.0.1", "[::1]")
                                .contains(uri.getHost());
        TrackingPolicy.require(
                uri.getHost() != null
                        && uri.getUserInfo() == null
                        && uri.getRawQuery() == null
                        && uri.getRawFragment() == null
                        && (uri.getRawPath() == null
                                || uri.getRawPath().isEmpty()
                                || uri.getRawPath().equals("/"))
                        && ("https".equals(uri.getScheme())
                                || local && "http".equals(uri.getScheme())),
                "fixed HTTPS public-base-url required");
        origin = uri.getScheme() + "://" + uri.getRawAuthority();
        baseUrl = origin;
        secure = "https".equals(uri.getScheme());
    }

    public void authorizeMutation(String suppliedOrigin, String csrf, String expected) {
        if (!origin.equals(suppliedOrigin)
                || csrf == null
                || expected == null
                || !MessageDigest.isEqual(
                        csrf.getBytes(StandardCharsets.UTF_8),
                        expected.getBytes(StandardCharsets.UTF_8)))
            throw new ResponseStatusException(
                    HttpStatus.FORBIDDEN, "origin and CSRF token required");
    }

    public void authorizeOrigin(String suppliedOrigin) {
        if (!origin.equals(suppliedOrigin))
            throw new ResponseStatusException(HttpStatus.FORBIDDEN, "configured origin required");
    }

    public String baseUrl() {
        return baseUrl;
    }

    public boolean secure() {
        return secure;
    }

    public static String token() {
        byte[] bytes = new byte[32];
        RANDOM.nextBytes(bytes);
        return Base64.getUrlEncoder().withoutPadding().encodeToString(bytes);
    }

    public static String email(String value) {
        TrackingPolicy.require(value != null, "email required");
        String email = value.trim().toLowerCase(Locale.ROOT);
        TrackingPolicy.require(
                email.length() <= 254
                        && email.matches(
                                "[a-z0-9.!#$%&'*+/=?^_`{|}~-]{1,64}@[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\\.[a-z]{2,63}"),
                "invalid email");
        return email;
    }

    static void tokenFormat(String token) {
        TrackingPolicy.require(
                token != null && token.matches("[A-Za-z0-9_-]{43}"), "invalid token");
    }
}
