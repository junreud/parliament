package dev.parliament.service;

import org.springframework.http.HttpHeaders;
import org.springframework.web.reactive.function.client.ClientResponse;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.core.publisher.Mono;

import java.net.URI;

public class WebClientSocialLinkClient implements SocialLinkClient {
    private final WebClient webClient;

    public WebClientSocialLinkClient(WebClient webClient) {
        this.webClient = webClient;
    }

    @Override
    public Mono<SocialLinkProbe> probe(URI uri) {
        return webClient.head()
                .uri(uri)
                .exchangeToMono(this::toProbe);
    }

    private Mono<SocialLinkProbe> toProbe(ClientResponse response) {
        String location = response.headers().asHttpHeaders().getFirst(HttpHeaders.LOCATION);
        SocialLinkProbe probe = new SocialLinkProbe(response.statusCode().value(), location);
        return response.releaseBody().thenReturn(probe);
    }
}
