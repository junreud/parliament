package dev.parliament.beta;

import java.time.Instant;
import java.util.HashMap;
import java.util.Map;
import org.springframework.http.HttpStatus;
import org.springframework.web.server.ResponseStatusException;

/** Bounded process-local abuse protection. Temporary peer keys are never written to storage. */
public final class BetaRateLimiter {
    private record Window(Instant expires, int count) {}
    private final Map<String, Window> windows = new HashMap<>();

    public synchronized void check(String peer, String action, int maximum, long seconds, Instant now) {
        windows.entrySet().removeIf(entry -> !entry.getValue().expires().isAfter(now));
        String key = action + ":" + peer;
        Window window = windows.get(key);
        if (window == null) {
            if (windows.size() >= 10000) limited();
            windows.put(key, new Window(now.plusSeconds(seconds), 1));
        } else {
            if (window.count() >= maximum) limited();
            windows.put(key, new Window(window.expires(), window.count() + 1));
        }
    }

    private static void limited() {
        throw new ResponseStatusException(HttpStatus.TOO_MANY_REQUESTS, "beta request limit");
    }
}
