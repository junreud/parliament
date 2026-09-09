package dev.parliament.controller;

import dev.parliament.config.ParliamentIngestionProperties;
import dev.parliament.service.ParliamentIngestionReport;
import dev.parliament.service.ParliamentIngestionRequest;
import dev.parliament.service.ParliamentIngestionService;
import dev.parliament.service.ParliamentSocialVerificationService;
import dev.parliament.service.ParliamentSyncReport;
import dev.parliament.service.ParliamentJobGuard;
import org.springframework.http.HttpStatus;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;
import reactor.core.publisher.Mono;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.Duration;

@RestController
@RequestMapping("/admin/ingestion/parliament")
@ConditionalOnProperty(prefix = "parliament.ingestion", name = "enabled", havingValue = "true")
public class ParliamentIngestionController {
    private static final String ADMIN_HEADER = "X-Parliament-Ingestion-Key";

    private final ParliamentIngestionService service;
    private final byte[] expectedAdminKey;
    private final ParliamentSocialVerificationService socialVerificationService;
    private final ParliamentJobGuard jobGuard;

    public ParliamentIngestionController(
            ParliamentIngestionService service,
            ParliamentSocialVerificationService socialVerificationService,
            ParliamentJobGuard jobGuard,
            ParliamentIngestionProperties properties
    ) {
        this.service = service;
        this.socialVerificationService = socialVerificationService;
        this.jobGuard = jobGuard;
        String adminKey = properties.getAdminKey();
        if (adminKey == null || adminKey.isBlank()) {
            throw new IllegalStateException("parliament.ingestion.admin-key is required");
        }
        this.expectedAdminKey = adminKey.getBytes(StandardCharsets.UTF_8);
    }

    @PostMapping("/sync")
    public Mono<ParliamentSyncReport> synchronize(
            @RequestHeader(ADMIN_HEADER) String adminKey,
            @RequestBody ParliamentIngestionRequest request
    ) {
        authorize(adminKey);
        return exclusive(mapClientErrors(Mono.defer(() -> service.synchronize(request))));
    }

    @PostMapping("/social/verify")
    public Mono<Integer> verifySocial(
            @RequestHeader(ADMIN_HEADER) String adminKey,
            @RequestParam(defaultValue = "7") int maxAgeDays,
            @RequestParam(defaultValue = "200") int limit
    ) {
        authorize(adminKey);
        return exclusive(mapClientErrors(Mono.defer(() -> socialVerificationService.verifyDue(
                Duration.ofDays(maxAgeDays), limit))));
    }

    @PostMapping("/preflight")
    public Mono<ParliamentIngestionReport> preflight(
            @RequestHeader(ADMIN_HEADER) String adminKey,
            @RequestBody ParliamentIngestionRequest request
    ) {
        authorize(adminKey);
        return mapClientErrors(Mono.defer(() -> service.preflight(request)));
    }

    @PostMapping("/run")
    public Mono<ParliamentIngestionReport> run(
            @RequestHeader(ADMIN_HEADER) String adminKey,
            @RequestBody ParliamentIngestionRequest request
    ) {
        authorize(adminKey);
        return Mono.defer(() -> {
            if (!jobGuard.tryAcquire()) {
                return Mono.error(new ResponseStatusException(
                        HttpStatus.CONFLICT, "parliament ingestion is already running"));
            }
            return mapClientErrors(Mono.defer(() -> service.run(request)))
                    .doFinally(signal -> jobGuard.release());
        });
    }

    private void authorize(String supplied) {
        byte[] suppliedBytes = supplied == null ? new byte[0] : supplied.getBytes(StandardCharsets.UTF_8);
        if (!MessageDigest.isEqual(expectedAdminKey, suppliedBytes)) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN, "invalid ingestion admin key");
        }
    }

    private <T> Mono<T> mapClientErrors(Mono<T> result) {
        return result.onErrorMap(IllegalArgumentException.class,
                error -> new ResponseStatusException(HttpStatus.BAD_REQUEST, error.getMessage(), error));
    }

    private <T> Mono<T> exclusive(Mono<T> operation) {
        return Mono.defer(() -> {
            if (!jobGuard.tryAcquire()) {
                return Mono.error(new ResponseStatusException(
                        HttpStatus.CONFLICT, "parliament ingestion is already running"));
            }
            return operation.doFinally(signal -> jobGuard.release());
        });
    }
}
