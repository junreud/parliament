package dev.parliament.service;

import java.net.URI;
import java.util.Locale;
import java.util.Set;

public class ParliamentSocialUrlPolicy {
    private static final Set<String> ALLOWED_HOSTS = Set.of(
            "x.com", "www.x.com", "twitter.com", "www.twitter.com",
            "youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be",
            "blog.naver.com", "m.blog.naver.com",
            "facebook.com", "www.facebook.com", "web.facebook.com", "m.facebook.com",
            "instagram.com", "www.instagram.com",
            "threads.net", "www.threads.net",
            "tiktok.com", "www.tiktok.com",
            "t.me", "telegram.me"
    );

    public URI requireAllowed(String rawUrl) {
        URI uri;
        try {
            uri = URI.create(rawUrl).normalize();
        } catch (RuntimeException error) {
            throw new IllegalArgumentException("invalid social URL", error);
        }
        String host = uri.getHost();
        if (!"https".equalsIgnoreCase(uri.getScheme())
                || host == null
                || !ALLOWED_HOSTS.contains(host.toLowerCase(Locale.ROOT))
                || uri.getUserInfo() != null
                || uri.getPort() != -1 && uri.getPort() != 443) {
            throw new IllegalArgumentException("social URL is outside the allowed platform hosts");
        }
        return uri;
    }
}
