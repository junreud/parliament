package dev.parliament.beta;

import org.junit.jupiter.api.Test;
import org.springframework.web.server.ResponseStatusException;
import java.time.Instant;
import java.util.Map;
import static org.assertj.core.api.Assertions.*;

class BetaPolicyTest {
    private final BetaPolicy policy = new BetaPolicy("https://beta.example.org");

    @Test
    void requiresExplicitConsentAndRejectsSensitiveOrUnknownFields() {
        assertThat(policy.enrollment(Map.of("email", "A@EXAMPLE.ORG", "consent", true,
                "cohort", "external", "source", "instagram")).email()).isEqualTo("a@example.org");
        assertThatThrownBy(() -> policy.enrollment(Map.of("email", "a@example.org", "consent", false,
                "cohort", "external", "source", "instagram"))).isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> policy.enrollment(Map.of("email", "a@example.org", "consent", true,
                "cohort", "external", "source", "instagram", "politicalView", "secret")))
                .isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> policy.event(Map.of("event", "source_opened", "visitKind", "organic",
                "issueId", "sensitive-topic"))).isInstanceOf(IllegalArgumentException.class);
    }

    @Test
    void onlyAcceptsBoundedDeclaredValuesAndRealEmail() {
        assertThatThrownBy(() -> policy.enrollment(Map.of("email", "wrong", "consent", true,
                "cohort", "external", "source", "instagram"))).isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> policy.event(Map.of("event", "arbitrary", "visitKind", "organic")))
                .isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> policy.event(Map.of("event", "source_opened", "visitKind", "ad")))
                .isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> policy.acquisition(Map.of("source", "instagram", "url", "https://example.org")))
                .isInstanceOf(IllegalArgumentException.class);
    }

    @Test
    void checksOriginCsrfAndHashesUnpredictableSessionTokens() {
        String token = policy.token();
        assertThat(token).matches("[A-Za-z0-9_-]{43}");
        assertThat(policy.hash(token)).hasSize(64).isNotEqualTo(token);
        policy.authorizeMutation("https://beta.example.org", "csrf", "csrf");
        assertThatThrownBy(() -> policy.authorizeMutation("https://other.example", "csrf", "csrf"))
                .isInstanceOf(ResponseStatusException.class);
        assertThatThrownBy(() -> policy.authorizeMutation("https://beta.example.org", null, "csrf"))
                .isInstanceOf(ResponseStatusException.class);
        assertThatThrownBy(() -> new BetaPolicy("http://public.example.org"))
                .isInstanceOf(IllegalArgumentException.class);
    }

    @Test
    void rateLimitExpiresAndDoesNotNeedPersistentIdentity() {
        BetaRateLimiter limiter = new BetaRateLimiter();
        Instant at = Instant.parse("2026-10-17T00:00:00Z");
        limiter.check("temporary-peer", "enrollment", 2, 60, at);
        limiter.check("temporary-peer", "enrollment", 2, 60, at);
        assertThatThrownBy(() -> limiter.check("temporary-peer", "enrollment", 2, 60, at))
                .isInstanceOf(ResponseStatusException.class);
        limiter.check("temporary-peer", "enrollment", 2, 60, at.plusSeconds(61));
    }
}
