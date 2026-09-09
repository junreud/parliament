package dev.parliament.config;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class ParliamentIngestionPropertiesTest {

    @Test
    void validatesAutomaticSyncBoundsAndStoresConfiguration() {
        ParliamentIngestionProperties properties = new ParliamentIngestionProperties();
        properties.setAutomaticEnabled(true);
        properties.setIncrementalPageSize(50);
        properties.setIncrementalMaxPages(20);
        properties.setSocialVerificationEnabled(false);
        properties.setSocialVerificationMaxAgeDays(3);
        properties.setSocialVerificationBatchSize(40);
        properties.setCaCertificatePath("local-ca.pem");

        assertThat(properties.isAutomaticEnabled()).isTrue();
        assertThat(properties.getIncrementalPageSize()).isEqualTo(50);
        assertThat(properties.getIncrementalMaxPages()).isEqualTo(20);
        assertThat(properties.isSocialVerificationEnabled()).isFalse();
        assertThat(properties.getSocialVerificationMaxAgeDays()).isEqualTo(3);
        assertThat(properties.getSocialVerificationBatchSize()).isEqualTo(40);
        assertThat(properties.getCaCertificatePath()).isEqualTo("local-ca.pem");

        assertThatThrownBy(() -> properties.setIncrementalPageSize(0))
                .isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> properties.setIncrementalMaxPages(0))
                .isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> properties.setSocialVerificationMaxAgeDays(0))
                .isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> properties.setSocialVerificationBatchSize(10_001))
                .isInstanceOf(IllegalArgumentException.class);
    }
}
