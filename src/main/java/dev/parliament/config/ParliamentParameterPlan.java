package dev.parliament.config;

import java.util.List;

public record ParliamentParameterPlan(
        String sourceKey,
        String officialInfId,
        ParameterPlanStatus status,
        List<ParliamentParameterBinding> bindings
) {
    public ParliamentParameterPlan {
        bindings = bindings == null ? List.of() : List.copyOf(bindings);
    }
}
