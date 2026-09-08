package dev.parliament.domain;

import org.junit.jupiter.api.Test;

import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

class ParliamentSocialAccountMapperTest {

    private final ParliamentSocialAccountMapper mapper = new ParliamentSocialAccountMapper();

    @Test
    void mapsAndCanonicalisesOfficialAssemblySocialLinks() {
        var accounts = mapper.map(Map.of(
                "TWITTER_URL", "https://twitter.com/example/",
                "YOUTUBE_URL", "https://www.youtube.com/@ExampleTV?view_as=subscriber",
                "BLOG_URL", "https://blog.naver.com/example",
                "FACEBOOK_URL", "example.page",
                "INSTAGRAM_URL", "@example_insta"
        ));

        assertThat(accounts).extracting(SocialAccount::platform)
                .containsExactlyInAnyOrder(
                        SocialPlatform.X,
                        SocialPlatform.YOUTUBE,
                        SocialPlatform.NAVER_BLOG,
                        SocialPlatform.FACEBOOK,
                        SocialPlatform.INSTAGRAM);
        assertThat(accounts).filteredOn(account -> account.platform() == SocialPlatform.X)
                .singleElement()
                .satisfies(account -> {
                    assertThat(account.url()).isEqualTo("https://x.com/example");
                    assertThat(account.handle()).isEqualTo("example");
                    assertThat(account.primary()).isTrue();
                    assertThat(account.verificationStatus()).isEqualTo(SocialVerificationStatus.OFFICIAL_DIRECTORY);
                });
    }

    @Test
    void rejectsNonHttpLinksAndUnknownHostsForKnownPlatforms() {
        var accounts = mapper.map(Map.of(
                "TWITTER_URL", "javascript:alert(1)",
                "YOUTUBE_URL", "https://example.com/not-youtube"
        ));

        assertThat(accounts).isEmpty();
    }

    @Test
    void keepsOnePrimaryAccountPerPlatformAndSupportsCommonAliases() {
        var accounts = mapper.map(Map.of(
                "TWITTER_URL", "https://x.com/primary",
                "X_URL", "https://x.com/duplicate",
                "YT_URL", "https://youtube.com/@channel",
                "THREADS_URL", "https://threads.net/@person",
                "TIKTOK_URL", "https://tiktok.com/@person",
                "TELEGRAM_URL", "https://t.me/person"
        ));

        assertThat(accounts).extracting(SocialAccount::platform)
                .containsExactly(
                        SocialPlatform.X,
                        SocialPlatform.YOUTUBE,
                        SocialPlatform.THREADS,
                        SocialPlatform.TIKTOK,
                        SocialPlatform.TELEGRAM);
        assertThat(accounts).filteredOn(account -> account.platform() == SocialPlatform.X)
                .singleElement()
                .extracting(SocialAccount::url)
                .isEqualTo("https://x.com/primary");
    }

    @Test
    void mapsActualOpenAssemblySnsFieldNames() {
        var accounts = mapper.map(Map.of(
                "T_URL", "https://twitter.com/member",
                "F_URL", "https://web.facebook.com/member",
                "Y_URL", "https://youtube.com/@member",
                "B_URL", "https://blog.naver.com/member"
        ));

        assertThat(accounts).extracting(SocialAccount::platform)
                .containsExactly(
                        SocialPlatform.X,
                        SocialPlatform.YOUTUBE,
                        SocialPlatform.NAVER_BLOG,
                        SocialPlatform.FACEBOOK);
        assertThat(accounts).filteredOn(account -> account.platform() == SocialPlatform.FACEBOOK)
                .singleElement()
                .extracting(SocialAccount::url)
                .isEqualTo("https://facebook.com/member");
    }
}
