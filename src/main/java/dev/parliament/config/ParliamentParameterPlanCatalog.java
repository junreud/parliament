package dev.parliament.config;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;

import java.io.IOException;
import java.io.InputStream;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;

public class ParliamentParameterPlanCatalog {
    private static final String DEFAULT_RESOURCE = "/parliament/open-assembly-parameter-plans.json";

    private final List<ParliamentParameterPlan> plans;
    private final Map<String, ParliamentParameterPlan> bySourceKey;

    private ParliamentParameterPlanCatalog(List<ParliamentParameterPlan> plans) {
        LinkedHashMap<String, ParliamentParameterPlan> unique = new LinkedHashMap<>();
        for (ParliamentParameterPlan plan : plans) {
            validate(plan);
            if (unique.putIfAbsent(plan.sourceKey(), plan) != null) {
                throw new IllegalArgumentException("duplicate parameter plan: " + plan.sourceKey());
            }
        }
        this.plans = List.copyOf(unique.values());
        this.bySourceKey = Map.copyOf(unique);
    }

    public static ParliamentParameterPlanCatalog loadDefault(ObjectMapper objectMapper) {
        try (InputStream input = ParliamentParameterPlanCatalog.class.getResourceAsStream(DEFAULT_RESOURCE)) {
            if (input == null) {
                throw new IllegalStateException("missing parliament parameter plans: " + DEFAULT_RESOURCE);
            }
            Map<String, Object> root = objectMapper.readValue(input, new TypeReference<>() { });
            List<ParliamentParameterPlan> plans = objectMapper.convertValue(
                    root.get("plans"), new TypeReference<>() { });
            return new ParliamentParameterPlanCatalog(plans);
        } catch (IOException error) {
            throw new IllegalStateException("failed to load parliament parameter plans", error);
        }
    }

    public static ParliamentParameterPlanCatalog of(List<ParliamentParameterPlan> plans) {
        return new ParliamentParameterPlanCatalog(plans);
    }

    public List<ParliamentParameterPlan> all() {
        return plans;
    }

    public Optional<ParliamentParameterPlan> find(String sourceKey) {
        return Optional.ofNullable(bySourceKey.get(sourceKey));
    }

    public ParliamentParameterPlan require(String sourceKey) {
        ParliamentParameterPlan plan = bySourceKey.get(sourceKey);
        if (plan == null) {
            throw new IllegalArgumentException("missing parameter plan: " + sourceKey);
        }
        return plan;
    }

    private void validate(ParliamentParameterPlan plan) {
        if (plan.sourceKey() == null || plan.sourceKey().isBlank()) {
            throw new IllegalArgumentException("parameter plan source key is required");
        }
        if (plan.officialInfId() == null || plan.officialInfId().isBlank()) {
            throw new IllegalArgumentException("official inf id is required: " + plan.sourceKey());
        }
        if (plan.status() == null) {
            throw new IllegalArgumentException("parameter plan status is required: " + plan.sourceKey());
        }
        if (plan.status() == ParameterPlanStatus.PARAMETERIZED && plan.bindings().isEmpty()) {
            throw new IllegalArgumentException("parameterized plan requires bindings: " + plan.sourceKey());
        }
        for (ParliamentParameterBinding binding : plan.bindings()) {
            if (binding.parameter() == null || !binding.parameter().matches("[A-Z0-9_]+")) {
                throw new IllegalArgumentException("invalid parameter name: " + plan.sourceKey());
            }
            if (binding.strategy() == ParameterValueStrategy.SOURCE_FIELD
                    && (isBlank(binding.sourceKey()) || isBlank(binding.sourceField()))) {
                throw new IllegalArgumentException("source field binding is incomplete: " + plan.sourceKey());
            }
            if (binding.strategy() == ParameterValueStrategy.LITERAL && isBlank(binding.sampleValue())) {
                throw new IllegalArgumentException("literal binding is empty: " + plan.sourceKey());
            }
        }
    }

    private boolean isBlank(String value) {
        return value == null || value.isBlank();
    }
}
