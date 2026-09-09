package dev.parliament.config;

public record ParliamentParameterBinding(
        String parameter,
        ParameterValueStrategy strategy,
        String sourceKey,
        String sourceField,
        String sampleValue
) {
}
