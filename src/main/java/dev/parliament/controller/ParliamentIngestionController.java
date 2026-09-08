package dev.parliament.controller;

import dev.parliament.config.ParliamentIngestionProperties;
import dev.parliament.service.ParliamentIngestionReport;
import dev.parliament.service.ParliamentIngestionRequest;
import dev.parliament.service.ParliamentIngestionService;
import org.springframework.http.HttpStatus;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;
import reactor.core.publisher.Mono;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;

@RestController
@RequestMapping("/admin/ingestion/parliament")
@ConditionalOnProperty(prefix = "parliament.ingestion", name = "enabled", havingValue = "true")
public class ParliamentIngestionController {
    private static final String ADMIN_HEADER = "X-Parliament-Ingestion-Key";

    private final ParliamentIngestionService service;
    private final byte[] expectedAdminKey;

    public ParliamentIngestionController(
            ParliamentIngestionService service,
            ParliamentIngestionProperties properties
    ) {
        this.service = service;
        String adminKey = properties.getAdminKey();
        if (adminKey == null || adminKey.isBlank()) {
            throw new IllegalStateException("parliament.ingestion.admin-key is required");
        }
        this.expectedAdminKey = adminKey.getBytes(StandardCharsets.UTF_8);
    }

    @PostMapping("/preflight")
    public Mono<ParliamentIngestionReport> preflight(
            @RequestHeader(ADMIN_HEADER) String adminKey,
            @RequestBody ParliamentIngestionRequest request
    ) {
        authorize(adminKey);
        return mapClientErrors(service.preflight(request));
    }

    @PostMapping("/run")
    public Mono<ParliamentIngestionReport> run(
            @RequestHeader(ADMIN_HEADER) String adminKey,
            @RequestBody ParliamentIngestionRequest request
    ) {
        authorize(adminKey);
        return mapClientErrors(service.run(request));
    }

    private void authorize(String supplied) {
        byte[] suppliedBytes = supplied == null ? new byte[0] : supplied.getBytes(StandardCharsets.UTF_8);
        if (!MessageDigest.isEqual(expectedAdminKey, suppliedBytes)) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN, "invalid ingestion admin key");
        }
    }

    private Mono<ParliamentIngestionReport> mapClientErrors(Mono<ParliamentIngestionReport> result) {
        return result.onErrorMap(IllegalArgumentException.class,
                error -> new ResponseStatusException(HttpStatus.BAD_REQUEST, error.getMessage(), error));
    }
}
