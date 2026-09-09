package dev.parliament.persistence;

import reactor.core.publisher.Flux;

import java.time.Instant;

public interface ParliamentParameterValueRepository {
    Flux<String> distinctRawValues(String sourceKey, String field, int limit);

    Flux<String> distinctRawValuesChangedSince(
            String sourceKey, String field, Instant changedSince, int limit);
}
