package dev.parliament.beta;

import dev.parliament.tracking.TrackingAuthPolicy;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.Duration;
import java.util.HexFormat;
import java.util.Map;
import java.util.Set;

/** Strict beta-only payload allowlists; never accepts issue identifiers or political opinions. */
public final class BetaPolicy {
    public static final Duration RETENTION = Duration.ofDays(35);
    public static final String CONSENT_VERSION = "beta-2026-10-v1";
    public static final Set<String> SOURCES = Set.of("instagram", "network", "community", "direct");
    public record Enrollment(String email, String cohort, String source) {}
    public record Event(String event, String visitKind) {}
    private final TrackingAuthPolicy auth;

    public BetaPolicy(String publicBaseUrl) {
        auth = new TrackingAuthPolicy(publicBaseUrl);
    }

    public Enrollment enrollment(Map<String, Object> input) {
        fields(input, Set.of("email", "consent", "cohort", "source"));
        require(Boolean.TRUE.equals(input.get("consent")));
        String cohort = text(input, "cohort");
        require(Set.of("friend", "external").contains(cohort));
        String source = text(input, "source");
        require(SOURCES.contains(source));
        return new Enrollment(TrackingAuthPolicy.email(text(input, "email")), cohort, source);
    }

    public Event event(Map<String, Object> input) {
        fields(input, Set.of("event", "visitKind"));
        String event = text(input, "event"), visitKind = text(input, "visitKind");
        require(Set.of("explainer_opened", "source_opened", "timeline_opened").contains(event));
        require(Set.of("organic", "research").contains(visitKind));
        return new Event(event, visitKind);
    }

    public String acquisition(Map<String, Object> input) {
        fields(input, Set.of("source"));
        String source = text(input, "source");
        require(SOURCES.contains(source));
        return source;
    }

    public void authorizeOrigin(String origin) { auth.authorizeOrigin(origin); }
    public void authorizeMutation(String origin, String csrf, String expected) {
        auth.authorizeMutation(origin, csrf, expected);
    }
    public boolean secure() { return auth.secure(); }
    public String token() { return TrackingAuthPolicy.token(); }
    public boolean validToken(String token) { return token != null && token.matches("[A-Za-z0-9_-]{43}"); }

    public String hash(String token) {
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256")
                    .digest(token.getBytes(StandardCharsets.UTF_8)));
        } catch (NoSuchAlgorithmException ex) {
            throw new IllegalStateException("SHA-256 required");
        }
    }

    private static void fields(Map<String, Object> input, Set<String> expected) {
        require(input != null && input.keySet().equals(expected));
    }
    private static String text(Map<String, Object> input, String key) {
        require(input.get(key) instanceof String);
        String value = (String) input.get(key);
        require(!value.isBlank() && value.length() <= 254);
        return value;
    }
    private static void require(boolean valid) {
        if (!valid) throw new IllegalArgumentException("invalid beta request");
    }
}
