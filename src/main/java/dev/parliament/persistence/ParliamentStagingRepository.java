package dev.parliament.persistence;

import dev.parliament.config.ParliamentSourceDefinition;
import dev.parliament.domain.NormalizedParliamentRecord;
import reactor.core.publisher.Mono;

import java.util.List;

public interface ParliamentStagingRepository {
    Mono<Integer> nextPage(String sourceKey);

    Mono<Void> savePage(
            ParliamentSourceDefinition source,
            List<NormalizedParliamentRecord> records,
            int currentPage,
            int nextPage,
            Boolean complete
    );
}

