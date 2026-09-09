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
import java.time.Instant;
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

    public Flux<ParliamentSourceDefinition> resolveAll(ParliamentSourceDefinition source) {
        return plans.find(source.key())
                .map(plan -> resolveAll(source, plan, null))
                .orElseGet(() -> Flux.just(source));
    }

    public Flux<ParliamentSourceDefinition> resolveChanged(
            ParliamentSourceDefinition source,
            Instant changedSince
    ) {
        if (changedSince == null) {
            return resolveAll(source);
        }
        return plans.find(source.key())
                .map(plan -> resolveAll(source, plan, changedSince))
                .orElseGet(() -> Flux.just(source));
    }

    public boolean dependsOnSourceRecords(ParliamentSourceDefinition source) {
        return plans.find(source.key())
                .stream()
                .flatMap(plan -> plan.bindings().stream())
                .anyMatch(binding -> binding.strategy()
                        == dev.parliament.config.ParameterValueStrategy.SOURCE_FIELD);
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

    private Flux<ParliamentSourceDefinition> resolveAll(
            ParliamentSourceDefinition source,
            ParliamentParameterPlan plan,
            Instant changedSince
    ) {
        if (plan.status() == ParameterPlanStatus.UNRESOLVED) {
            return Flux.error(new IllegalStateException(
                    "unresolved parameter contract for source " + source.key()));
        }
        if (plan.status() != ParameterPlanStatus.PARAMETERIZED) {
            return Flux.just(source);
        }
        Flux<Map<String, String>> combinations = Flux.just(Map.of());
        for (ParliamentParameterBinding binding : plan.bindings()) {
            Flux<String> values = resolveAllValues(binding, changedSince).cache();
            combinations = combinations.concatMap(parameters -> values.map(value -> {
                LinkedHashMap<String, String> expanded = new LinkedHashMap<>(parameters);
                expanded.put(binding.parameter(), value);
                return Map.copyOf(expanded);
            }));
        }
        return combinations.map(source::withFixedParams);
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

    private Flux<String> resolveAllValues(
            ParliamentParameterBinding binding,
            Instant changedSince
    ) {
        if (binding.strategy() != dev.parliament.config.ParameterValueStrategy.SOURCE_FIELD) {
            return resolve(binding).flux();
        }
        Flux<String> values = changedSince == null
                ? valueRepository.distinctRawValues(binding.sourceKey(), binding.sourceField(), 100_000)
                : valueRepository.distinctRawValuesChangedSince(
                        binding.sourceKey(), binding.sourceField(), changedSince, 100_000);
        return changedSince == null
                ? values.switchIfEmpty(Flux.error(new IllegalStateException(
                        "no source values for required parameter " + binding.parameter()
                                + " from " + binding.sourceKey() + "." + binding.sourceField())))
                : values;
    }

    private Mono<String> fallback(ParliamentParameterBinding binding) {
        if (binding.sampleValue() == null || binding.sampleValue().isBlank()) {
            return Mono.error(new IllegalStateException(
                    "no source value for required parameter " + binding.parameter()));
        }
        return Mono.just(binding.sampleValue());
    }
}
