package dev.parliament.knowledge;

import java.time.Duration;
import org.junit.jupiter.api.Test;
import reactor.core.publisher.Mono;
import reactor.test.StepVerifier;

class KnowledgeGraphLimitsTest {
    @Test void unresponsiveReadsFailWithinTheReadBudget() {
        StepVerifier.withVirtualTime(()->KnowledgeGraphLimits.timed(Mono.never()))
                .thenAwait(Duration.ofSeconds(10))
                .expectErrorMatches(error->error.getMessage().contains("503")&&error.getMessage().contains("bounded read budget"))
                .verify();
    }
}
