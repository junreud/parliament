package dev.parliament.api;

import dev.parliament.config.ParliamentIngestionProperties;
import dev.parliament.config.ParliamentSourceDefinition;
import org.springframework.core.io.buffer.DataBuffer;
import org.springframework.core.io.buffer.DataBufferUtils;
import org.springframework.web.reactive.function.client.WebClient;
import org.springframework.web.reactive.function.client.WebClientRequestException;
import reactor.core.publisher.Mono;

import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.Objects;
import java.util.regex.Pattern;

public class WebClientParliamentApiClient implements ParliamentApiClient {
    private static final String OFFICIAL_HOST = "open.assembly.go.kr";
    private static final String USER_AGENT =
            "Mozilla/5.0 (compatible; ParliamentDataPlatform/1.0; +https://github.com/junreud/parliament)";
    private static final int MAX_RESPONSE_BYTES = 10 * 1024 * 1024;
    private static final Pattern API_CODE = Pattern.compile("[A-Za-z0-9]+$");

    private final WebClient webClient;
    private final OpenAssemblyResponseParser parser;
    private final URI baseUri;
    private final String apiKey;

    public WebClientParliamentApiClient(
            WebClient webClient,
            ParliamentIngestionProperties properties,
            OpenAssemblyResponseParser parser
    ) {
        this.webClient = Objects.requireNonNull(webClient);
        this.parser = Objects.requireNonNull(parser);
        this.apiKey = requireApiKey(properties.getApiKey());
        this.baseUri = requireOfficialBaseUri(properties.getBaseUrl());
    }

    @Override
    public Mono<OpenAssemblyPage> fetch(ParliamentSourceDefinition source, int page, int pageSize) {
        if (!API_CODE.matcher(source.apiCode()).matches()) {
            return Mono.error(new IllegalArgumentException("invalid Open Assembly api code"));
        }
        return webClient.get()
                .uri(builder -> {
                    builder.scheme(baseUri.getScheme()).host(baseUri.getHost()).path(baseUri.getPath())
                            .pathSegment(source.apiCode())
                            .queryParam("Type", "json")
                            .queryParam("pIndex", page)
                            .queryParam("pSize", pageSize);
                    source.fixedParams().forEach(builder::queryParam);
                    return builder.queryParam("KEY", apiKey).build();
                })
                .header("User-Agent", USER_AGENT)
                .exchangeToMono(response -> {
                    if (response.statusCode().isError()) {
                        return Mono.error(new OpenAssemblyApiException(
                                "Open Assembly HTTP error " + response.statusCode().value()));
                    }
                    return DataBufferUtils.join(response.bodyToFlux(DataBuffer.class),
                                    MAX_RESPONSE_BYTES)
                            .map(buffer -> {
                                try {
                                    byte[] body = new byte[buffer.readableByteCount()];
                                    buffer.read(body);
                                    return new String(body, StandardCharsets.UTF_8);
                                } finally {
                                    DataBufferUtils.release(buffer);
                                }
                            });
                })
                .timeout(Duration.ofSeconds(20))
                .map(body -> parser.parse(source.apiCode(), body))
                .onErrorMap(WebClientRequestException.class,
                        error -> new OpenAssemblyApiException("Open Assembly request failed"));
    }

    private String requireApiKey(String value) {
        if (value == null || value.isBlank()) {
            throw new IllegalStateException("parliament.ingestion.api-key is required");
        }
        return value;
    }

    private URI requireOfficialBaseUri(String value) {
        URI uri;
        try {
            uri = URI.create(value);
        } catch (RuntimeException error) {
            throw new IllegalArgumentException("base URL must use https://open.assembly.go.kr", error);
        }
        if (!"https".equalsIgnoreCase(uri.getScheme())
                || !OFFICIAL_HOST.equalsIgnoreCase(uri.getHost())
                || uri.getUserInfo() != null
                || uri.getPort() != -1) {
            throw new IllegalArgumentException("base URL must use https://open.assembly.go.kr");
        }
        return uri;
    }
}
