package dev.parliament.service;

import dev.parliament.config.ParameterPlanStatus;
import dev.parliament.config.ParliamentIngestionProperties;
import dev.parliament.config.ParliamentParameterBinding;
import dev.parliament.config.ParliamentParameterPlan;
import dev.parliament.config.ParliamentParameterPlanCatalog;
import dev.parliament.config.ParliamentSourceDefinition;
import dev.parliament.persistence.ParliamentParameterValueRepository;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;

import java.time.Clock;
import java.time.LocalDate;
import java.util.LinkedHashMap;
import java.util.Map;

public class ParliamentParameterResolver {
    private final ParliamentParameterPlanCatalog plans;
    private final ParliamentParameterValueRepository valueRepository;
    private final ParliamentIngestionProperties properties;
    private final Clock clock;

    public ParliamentParameterResolver(
            ParliamentParameterPlanCatalog plans,
            ParliamentParameterValueRepository valueRepository,
            ParliamentIngestionProperties properties,
            Clock clock
    ) {
        this.plans = plans;
        this.valueRepository = valueRepository;
        this.properties = properties;
        this.clock = clock;
    }

    public Mono<ParliamentSourceDefinition> resolveSample(ParliamentSourceDefinition source) {
        return plans.find(source.key())
                .map(plan -> resolveSample(source, plan))
                .orElseGet(() -> Mono.just(source));
    }

    public Mono<ParliamentSourceDefinition> resolveSample(
            ParliamentSourceDefinition source,
            ParliamentParameterPlan plan
    ) {
        if (plan.status() == ParameterPlanStatus.UNRESOLVED) {
            return Mono.error(new IllegalStateException(
                    "unresolved parameter contract for source " + source.key()));
        }
        if (plan.status() != ParameterPlanStatus.PARAMETERIZED) {
            return Mono.just(source);
        }
        return Flux.fromIterable(plan.bindings())
                .concatMap(binding -> resolve(binding)
                        .map(value -> Map.entry(binding.parameter(), value)))
                .collect(LinkedHashMap<String, String>::new,
                        (parameters, entry) -> parameters.put(entry.getKey(), entry.getValue()))
                .map(source::withFixedParams);
    }

    private Mono<String> resolve(ParliamentParameterBinding binding) {
        int assembly = properties.getCurrentAssemblyNumber();
        LocalDate today = LocalDate.now(clock);
        return switch (binding.strategy()) {
            case CURRENT_ASSEMBLY_NUMBER -> Mono.just(Integer.toString(assembly));
            case CURRENT_ASSEMBLY_LABEL -> Mono.just("제" + assembly + "대");
            case CURRENT_ASSEMBLY_UNIT_CODE -> Mono.just("1000" + String.format("%02d", assembly));
            case CURRENT_YEAR -> Mono.just(Integer.toString(today.getYear()));
            case CURRENT_DATE -> Mono.just(today.toString());
            case LITERAL -> Mono.just(binding.sampleValue());
            case SOURCE_FIELD -> valueRepository.distinctRawValues(
                            binding.sourceKey(), binding.sourceField(), 1)
                    .next()
                    .switchIfEmpty(Mono.defer(() -> fallback(binding)));
        };
    }

    private Mono<String> fallback(ParliamentParameterBinding binding) {
        if (binding.sampleValue() == null || binding.sampleValue().isBlank()) {
            return Mono.error(new IllegalStateException(
                    "no source value for required parameter " + binding.parameter()));
        }
        return Mono.just(binding.sampleValue());
    }
}
