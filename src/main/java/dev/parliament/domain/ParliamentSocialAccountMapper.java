package dev.parliament.domain;

import java.net.URI;
import java.net.URISyntaxException;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Optional;

public class ParliamentSocialAccountMapper {
    private static final List<FieldPlatform> FIELD_PLATFORMS = List.of(
            new FieldPlatform("TWITTER_URL", SocialPlatform.X),
            new FieldPlatform("X_URL", SocialPlatform.X),
            new FieldPlatform("T_URL", SocialPlatform.X),
            new FieldPlatform("YOUTUBE_URL", SocialPlatform.YOUTUBE),
            new FieldPlatform("YT_URL", SocialPlatform.YOUTUBE),
            new FieldPlatform("Y_URL", SocialPlatform.YOUTUBE),
            new FieldPlatform("BLOG_URL", SocialPlatform.NAVER_BLOG),
            new FieldPlatform("B_URL", SocialPlatform.NAVER_BLOG),
            new FieldPlatform("FACEBOOK_URL", SocialPlatform.FACEBOOK),
            new FieldPlatform("FB_URL", SocialPlatform.FACEBOOK),
            new FieldPlatform("F_URL", SocialPlatform.FACEBOOK),
            new FieldPlatform("INSTAGRAM_URL", SocialPlatform.INSTAGRAM),
            new FieldPlatform("INSTA_URL", SocialPlatform.INSTAGRAM),
            new FieldPlatform("THREADS_URL", SocialPlatform.THREADS),
            new FieldPlatform("TIKTOK_URL", SocialPlatform.TIKTOK),
            new FieldPlatform("TELEGRAM_URL", SocialPlatform.TELEGRAM)
    );

    public List<SocialAccount> map(Map<String, Object> row) {
        Map<SocialPlatform, SocialAccount> accounts = new LinkedHashMap<>();
        FIELD_PLATFORMS.forEach(mapping -> Optional.ofNullable(row.get(mapping.field()))
                .map(Object::toString)
                .flatMap(value -> canonicalize(mapping.platform(), value))
                .ifPresent(account -> accounts.putIfAbsent(account.platform(), account)));
        return List.copyOf(accounts.values());
    }

    private Optional<SocialAccount> canonicalize(SocialPlatform platform, String rawValue) {
        String raw = rawValue == null ? "" : rawValue.trim();
        if (raw.isBlank()) {
            return Optional.empty();
        }

        String expanded = expandHandle(platform, raw);
        try {
            URI parsed = new URI(expanded);
            if (!"https".equalsIgnoreCase(parsed.getScheme()) || parsed.getHost() == null) {
                return Optional.empty();
            }
            String host = parsed.getHost().toLowerCase(Locale.ROOT);
            if (!allowedHost(platform, host)) {
                return Optional.empty();
            }
            String path = parsed.getPath() == null ? "" : parsed.getPath().replaceAll("/+$", "");
            String handle = lastPathPart(path).replaceFirst("^@", "");
            String canonicalHost = platform == SocialPlatform.X ? "x.com" : host.replaceFirst("^www\\.", "");
            String canonicalUrl = "https://" + canonicalHost + path;
            return Optional.of(new SocialAccount(
                    platform,
                    canonicalUrl,
                    handle.isBlank() ? null : handle,
                    true,
                    SocialVerificationStatus.OFFICIAL_DIRECTORY
            ));
        } catch (URISyntaxException error) {
            return Optional.empty();
        }
    }

    private String expandHandle(SocialPlatform platform, String raw) {
        if (raw.startsWith("http://") || raw.startsWith("https://") || raw.contains(":")) {
            return raw;
        }
        String handle = raw.replaceFirst("^@", "");
        return switch (platform) {
            case X -> "https://x.com/" + handle;
            case YOUTUBE -> "https://youtube.com/" + (raw.startsWith("@") ? raw : "@" + handle);
            case NAVER_BLOG -> "https://blog.naver.com/" + handle;
            case FACEBOOK -> "https://facebook.com/" + handle;
            case INSTAGRAM -> "https://instagram.com/" + handle;
            case THREADS -> "https://threads.net/@" + handle;
            case TIKTOK -> "https://tiktok.com/@" + handle;
            case TELEGRAM -> "https://t.me/" + handle;
            default -> raw;
        };
    }

    private boolean allowedHost(SocialPlatform platform, String host) {
        return switch (platform) {
            case X -> host.equals("x.com") || host.equals("twitter.com") || host.equals("www.twitter.com");
            case YOUTUBE -> host.equals("youtube.com") || host.equals("www.youtube.com") || host.equals("youtu.be");
            case NAVER_BLOG -> host.equals("blog.naver.com") || host.equals("m.blog.naver.com");
            case FACEBOOK -> host.equals("facebook.com") || host.equals("www.facebook.com");
            case INSTAGRAM -> host.equals("instagram.com") || host.equals("www.instagram.com");
            case THREADS -> host.equals("threads.net") || host.equals("www.threads.net");
            case TIKTOK -> host.equals("tiktok.com") || host.equals("www.tiktok.com");
            case TELEGRAM -> host.equals("t.me") || host.equals("telegram.me");
            default -> false;
        };
    }

    private String lastPathPart(String path) {
        if (path == null || path.isBlank()) {
            return "";
        }
        int index = path.lastIndexOf('/');
        return index >= 0 ? path.substring(index + 1) : path;
    }

    private record FieldPlatform(String field, SocialPlatform platform) {
    }
}
