package dev.parliament.service;

import reactor.core.publisher.Mono;

import java.net.URI;

public interface SocialLinkClient {
    Mono<SocialLinkProbe> probe(URI uri);
}
