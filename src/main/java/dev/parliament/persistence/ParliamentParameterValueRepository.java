package dev.parliament.persistence;

import reactor.core.publisher.Flux;

public interface ParliamentParameterValueRepository {
    Flux<String> distinctRawValues(String sourceKey, String field, int limit);
}
