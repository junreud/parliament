package dev.parliament.beta;

import java.time.Instant;
import org.junit.jupiter.api.Test;
import org.springframework.r2dbc.core.DatabaseClient;
import org.springframework.web.server.ResponseStatusException;
import reactor.core.publisher.Mono;
import reactor.test.StepVerifier;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

class BetaRepositoryFailureTest {
    @Test
    void databaseFailureIsUnavailableWithoutLeakingDriverOrContactDetails() {
        DatabaseClient database = mock(DatabaseClient.class, RETURNS_DEEP_STUBS);
        DatabaseClient.GenericExecuteSpec query = database.sql(anyString());
        when(query.bind(anyString(), any())).thenReturn(query);
        when(query.map(org.mockito.ArgumentMatchers.<java.util.function.BiFunction<io.r2dbc.spi.Row, io.r2dbc.spi.RowMetadata, BetaRepository.Session>>any()).one()).thenReturn(
                Mono.error(new IllegalStateException("database details fake-person@example.org")));
        BetaRepository repository = new BetaRepository(database, null, new BetaPolicy("http://localhost:3000"));
        StepVerifier.create(repository.current("a".repeat(43), Instant.EPOCH)).expectErrorSatisfies(error -> {
            assertThat(error).isInstanceOf(ResponseStatusException.class);
            assertThat(((ResponseStatusException)error).getStatusCode().value()).isEqualTo(503);
            assertThat(error.getMessage()).doesNotContain("fake-person", "database details");
            assertThat(error.getCause()).isNull();
        }).verify();
    }
}
