package dev.parliament.api;

import dev.parliament.config.ParliamentSourceDefinition;
import reactor.core.publisher.Mono;

public interface ParliamentApiClient {
    Mono<OpenAssemblyPage> fetch(ParliamentSourceDefinition source, int page, int pageSize);
}

