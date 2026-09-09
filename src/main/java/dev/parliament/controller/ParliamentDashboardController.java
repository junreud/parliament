package dev.parliament.controller;

import dev.parliament.config.ParliamentIngestionProperties;
import dev.parliament.service.ParliamentDashboardService;
import dev.parliament.service.ParliamentDashboardSnapshot;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.format.annotation.DateTimeFormat;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;
import reactor.core.publisher.Mono;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.LocalDate;

@RestController
@RequestMapping("/api/v1/parliament-ingestion-dashboard")
@ConditionalOnProperty(prefix = "parliament.ingestion", name = "enabled", havingValue = "true")
public class ParliamentDashboardController {
    private static final String ADMIN_HEADER = "X-Parliament-Ingestion-Key";
    private final ParliamentDashboardService service;
    private final byte[] expectedAdminKey;

    public ParliamentDashboardController(
            ParliamentDashboardService service,
            ParliamentIngestionProperties properties
    ) {
        this.service = service;
        String adminKey = properties.getAdminKey();
        if (adminKey == null || adminKey.isBlank()) {
            throw new IllegalStateException("parliament.ingestion.admin-key is required");
        }
        expectedAdminKey = adminKey.getBytes(StandardCharsets.UTF_8);
    }

    @GetMapping
    public Mono<ParliamentDashboardSnapshot> snapshot(
            @RequestHeader(ADMIN_HEADER) String adminKey,
            @RequestParam(required = false)
            @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate date,
            @RequestParam(defaultValue = "30") int days
    ) {
        authorize(adminKey);
        return Mono.defer(() -> service.snapshot(date, days))
                .onErrorMap(IllegalArgumentException.class,
                        error -> new ResponseStatusException(HttpStatus.BAD_REQUEST, error.getMessage()));
    }

    private void authorize(String candidate) {
        byte[] supplied = candidate == null
                ? new byte[0]
                : candidate.getBytes(StandardCharsets.UTF_8);
        if (!MessageDigest.isEqual(expectedAdminKey, supplied)) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN, "invalid admin key");
        }
    }
}
