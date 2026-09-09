package dev.parliament.api;

import dev.parliament.config.ParliamentIngestionProperties;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.web.reactive.function.client.WebClient;

import java.nio.file.Files;
import java.nio.file.Path;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class OpenAssemblyWebClientFactoryTest {

    @Test
    void usesSystemTrustWhenNoLocalCertificateIsConfigured() {
        ParliamentIngestionProperties properties = new ParliamentIngestionProperties();

        assertThat(new OpenAssemblyWebClientFactory().create(WebClient.builder(), properties))
                .isNotNull();
    }

    @Test
    void rejectsMissingOrInvalidCertificateFiles(@TempDir Path tempDir) throws Exception {
        ParliamentIngestionProperties properties = new ParliamentIngestionProperties();
        properties.setCaCertificatePath(tempDir.resolve("missing.pem").toString());
        assertThatThrownBy(() -> new OpenAssemblyWebClientFactory()
                .create(WebClient.builder(), properties))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("does not exist");

        Path invalid = tempDir.resolve("invalid.pem");
        Files.writeString(invalid, "not a certificate");
        properties.setCaCertificatePath(invalid.toString());
        assertThatThrownBy(() -> new OpenAssemblyWebClientFactory()
                .create(WebClient.builder(), properties))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("invalid");
    }
}
