package dev.parliament.knowledge;

import com.fasterxml.jackson.databind.ObjectMapper;
import dev.parliament.tracking.TrackingRepository;
import io.r2dbc.spi.ConnectionFactory;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;
import org.springframework.http.HttpStatus;
import org.springframework.r2dbc.core.DatabaseClient;
import org.springframework.web.server.ResponseStatusException;

import static org.assertj.core.api.Assertions.assertThat;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

class KnowledgeConfigurationTest {
    @TempDir Path directory;

    @Test
    void configuredLocalCatalogIsRereadInsteadOfThePackagedDefault() throws IOException {
        Path catalog = directory.resolve("catalog.json");
        Files.writeString(catalog, "{\"publications\":[]}");
        runner().withPropertyValues("knowledge.reading-catalog=" + catalog.toUri())
                .run(context -> {
                    assertThat(context).hasNotFailed();
                    var readings = context.getBean(IssueReadingCatalog.class);
                    assertThat(assertThrows(ResponseStatusException.class,
                            () -> readings.find("synthetic-issue")).getStatusCode())
                            .isEqualTo(HttpStatus.NOT_FOUND);

                    Files.writeString(catalog, "{malformed");
                    assertThat(assertThrows(ResponseStatusException.class,
                            () -> readings.find("synthetic-issue")).getStatusCode())
                            .isEqualTo(HttpStatus.SERVICE_UNAVAILABLE);
                });
    }

    @Test
    void configuredRemoteCatalogIsRejectedBeforeFetching() throws IOException {
        runner().withPropertyValues(
                        "knowledge.reading-catalog=https://example.invalid/catalog.json")
                .run(context -> {
                    assertThat(context).hasFailed();
                    assertThat(context.getStartupFailure())
                            .hasRootCauseInstanceOf(IOException.class)
                            .hasStackTraceContaining("remote source forbidden");
                });
    }

    @Test
    void packagedCatalogRemainsTheDefault() throws IOException {
        runner().run(context -> assertThat(context)
                .hasNotFailed().hasSingleBean(IssueReadingCatalog.class));
    }

    private ApplicationContextRunner runner() throws IOException {
        Path source = directory.resolve("editorial.json");
        Files.writeString(source, "{\"issues\":[]}");
        var factory = mock(ConnectionFactory.class);
        var db = mock(DatabaseClient.class);
        when(db.getConnectionFactory()).thenReturn(factory);
        return new ApplicationContextRunner()
                .withUserConfiguration(KnowledgeConfiguration.class)
                .withPropertyValues("knowledge.enabled=true",
                        "knowledge.editorial-source=" + source.toUri())
                .withBean(ObjectMapper.class, ObjectMapper::new)
                .withBean(ConnectionFactory.class, () -> factory)
                .withBean(DatabaseClient.class, () -> db)
                .withBean(TrackingRepository.class, () -> mock(TrackingRepository.class))
                .withBean(KnowledgeIdentity.class, () -> mock(KnowledgeIdentity.class));
    }
}
