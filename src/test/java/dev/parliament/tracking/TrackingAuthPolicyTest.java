package dev.parliament.tracking;

import static org.assertj.core.api.Assertions.*;

import org.junit.jupiter.api.Test;

class TrackingAuthPolicyTest {
    @Test
    void onlyConfiguredOriginCanMutateAndCsrfMustMatch() {
        TrackingAuthPolicy policy = new TrackingAuthPolicy("https://example.test");
        assertThatCode(
                        () ->
                                policy.authorizeMutation(
                                        "https://example.test", "test-csrf", "test-csrf"))
                .doesNotThrowAnyException();
        assertThatThrownBy(
                        () ->
                                policy.authorizeMutation(
                                        "https://evil.test", "test-csrf", "test-csrf"))
                .isInstanceOf(org.springframework.web.server.ResponseStatusException.class);
        assertThatThrownBy(
                        () -> policy.authorizeMutation("https://example.test", null, "test-csrf"))
                .isInstanceOf(org.springframework.web.server.ResponseStatusException.class);
    }

    @Test
    void unsafePublicBaseFailsAndTokensAreRandomAndHashed() {
        assertThatThrownBy(() -> new TrackingAuthPolicy("https://user@example.test"))
                .isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> new TrackingAuthPolicy("http://example.test"))
                .isInstanceOf(IllegalArgumentException.class);
        String one = TrackingAuthPolicy.token(), two = TrackingAuthPolicy.token();
        assertThat(one).hasSize(43).isNotEqualTo(two);
        assertThat(TrackingRepository.hash(one)).doesNotContain(one);
    }

    @Test
    void emailValidationRejectsHeaderInjectionAndArbitraryUrl() {
        assertThat(TrackingAuthPolicy.email(" USER@example.test ")).isEqualTo("user@example.test");
        assertThatThrownBy(
                        () ->
                                TrackingAuthPolicy.email(
                                        "user@example.test\r\nBCC:another@example.test"))
                .isInstanceOf(IllegalArgumentException.class);
    }
}
