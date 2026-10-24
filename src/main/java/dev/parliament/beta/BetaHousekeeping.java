package dev.parliament.beta;

import java.time.Clock;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.scheduling.annotation.Scheduled;
import reactor.core.publisher.Mono;

/** Ten-minute cleanup with one-hour early erasure keeps healthy operation within the 35-day cap. */
public final class BetaHousekeeping {
    private static final Logger LOG = LoggerFactory.getLogger(BetaHousekeeping.class);
    private final BetaRetention retention;
    private final Clock clock;
    public BetaHousekeeping(BetaRetention retention, Clock clock) {
        this.retention = retention;
        this.clock = clock;
    }

    @Scheduled(fixedDelay = 600000)
    public Mono<Void> purge() {
        return Mono.defer(() -> retention.purge(clock.instant())).onErrorResume(error -> {
            LOG.warn("Beta retention cleanup unavailable; retry on next scheduled run");
            return Mono.empty();
        });
    }
}
