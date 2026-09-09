package dev.parliament.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import dev.parliament.config.ParameterPlanStatus;
import dev.parliament.config.ParameterValueStrategy;
import dev.parliament.config.ParliamentCollectionMode;
import dev.parliament.config.ParliamentIngestionProperties;
import dev.parliament.config.ParliamentMediaType;
import dev.parliament.config.ParliamentParameterBinding;
import dev.parliament.config.ParliamentParameterPlan;
import dev.parliament.config.ParliamentParameterPlanCatalog;
import dev.parliament.config.ParliamentSourceDefinition;
import dev.parliament.persistence.ParliamentParameterValueRepository;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import reactor.core.publisher.Flux;
import reactor.test.StepVerifier;

import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class ParliamentParameterResolverTest {
    @Mock private ParliamentParameterValueRepository valueRepository;

    private ParliamentIngestionProperties properties;
    private ParliamentParameterResolver resolver;

    @BeforeEach
    void setUp() {
        properties = new ParliamentIngestionProperties();
        properties.setCurrentAssemblyNumber(22);
        resolver = new ParliamentParameterResolver(
                ParliamentParameterPlanCatalog.loadDefault(new ObjectMapper()),
                valueRepository,
                properties,
                Clock.fixed(Instant.parse("2026-09-09T00:00:00Z"), ZoneOffset.UTC));
    }

    @Test
    void resolvesCurrentAssemblyUnitYearAndDateWithoutHardcodedCatalogValues() {
        ParliamentParameterPlan plan = new ParliamentParameterPlan(
                "sample", "OFFICIAL-ID", ParameterPlanStatus.PARAMETERIZED,
                List.of(
                        new ParliamentParameterBinding("AGE", ParameterValueStrategy.CURRENT_ASSEMBLY_NUMBER,
                                null, null, null),
                        new ParliamentParameterBinding("ERACO", ParameterValueStrategy.CURRENT_ASSEMBLY_LABEL,
                                null, null, null),
                        new ParliamentParameterBinding("UNIT_CD", ParameterValueStrategy.CURRENT_ASSEMBLY_UNIT_CODE,
                                null, null, null),
                        new ParliamentParameterBinding("YEAR", ParameterValueStrategy.CURRENT_YEAR,
                                null, null, null),
                        new ParliamentParameterBinding("DT", ParameterValueStrategy.CURRENT_DATE,
                                null, null, null)));

        StepVerifier.create(resolver.resolveSample(source("sample"), plan))
                .assertNext(resolved -> assertThat(resolved.fixedParams()).containsAllEntriesOf(Map.of(
                        "AGE", "22",
                        "ERACO", "제22대",
                        "UNIT_CD", "100022",
                        "YEAR", "2026",
                        "DT", "2026-09-09")))
                .verifyComplete();
    }

    @Test
    void resolvesDependentIdentifiersFromAlreadyIngestedParentRecords() {
        when(valueRepository.distinctRawValues("billrcp", "BILL_NO", 1))
                .thenReturn(Flux.just("2200001"));

        StepVerifier.create(resolver.resolveSample(source("allbill")))
                .assertNext(resolved -> assertThat(resolved.fixedParams())
                        .containsEntry("BILL_NO", "2200001"))
                .verifyComplete();
    }

    @Test
    void reportsUndocumentedRequiredParameterInsteadOfGuessing() {
        StepVerifier.create(resolver.resolveSample(source("namemberevent")))
                .expectErrorMatches(error -> error instanceof IllegalStateException
                        && error.getMessage().contains("unresolved parameter contract"))
                .verify();
    }

    private ParliamentSourceDefinition source(String key) {
        return new ParliamentSourceDefinition(
                key, key, key, null, ParliamentMediaType.DATA, ParliamentCollectionMode.PAGE, Map.of());
    }
}
