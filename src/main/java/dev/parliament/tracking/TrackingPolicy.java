package dev.parliament.tracking;

import java.net.URI;
import java.util.Set;

public final class TrackingPolicy {
    private static final Set<String> HOSTS =
            Set.of(
                    "assembly.go.kr",
                    "nanet.go.kr",
                    "mogef.go.kr",
                    "president.go.kr",
                    "opm.go.kr",
                    "korea.kr",
                    "law.go.kr",
                    "lawmaking.go.kr",
                    "nec.go.kr", "org.go.kr", "gaok.or.kr", "namk.or.kr",
                    "mcee.go.kr", "mods.go.kr", "mofe.go.kr", "moj.go.kr",
                    "naacc.go.kr", "pipc.go.kr", "acrc.go.kr", "bai.go.kr",
                    "cio.go.kr", "customs.go.kr", "dapa.go.kr", "forest.go.kr",
                    "fsc.go.kr", "ftc.go.kr", "humanrights.go.kr", "kasa.go.kr",
                    "kcg.go.kr", "kdca.go.kr", "khs.go.kr", "kmcc.go.kr",
                    "mafra.go.kr", "mcst.go.kr", "mfds.go.kr", "mma.go.kr",
                    "mnd.go.kr", "moe.go.kr", "moel.go.kr", "mof.go.kr", "mofa.go.kr",
                    "mohw.go.kr", "moip.go.kr", "mois.go.kr", "moleg.go.kr",
                    "molit.go.kr", "motir.go.kr", "mpb.go.kr", "mpm.go.kr",
                    "mpva.go.kr", "msit.go.kr", "mss.go.kr", "ne.go.kr",
                    "nfa.go.kr", "nis.go.kr", "nssc.go.kr", "nts.go.kr",
                    "oka.go.kr", "police.go.kr", "pps.go.kr", "rda.go.kr", "ktv.go.kr",
                    "saemangeum.go.kr", "spo.go.kr", "unikorea.go.kr", "weather.go.kr", "jejusi.go.kr", "seogwipo.go.kr", "goryeong.go.kr", "jeju.go.kr", "pss.go.kr", "kma.go.kr", "neac.go.kr", "pacst.go.kr", "puac.go.kr");
    private static final Set<String> VOTES = Set.of("yes", "no", "abstain", "absent", "unknown");
    private static final Set<String> TYPES =
            Set.of("bill", "vote", "announcement", "speech", "meeting", "law");
    private static final Set<String> STAGES =
            Set.of(
                    "announced",
                    "scheduled",
                    "proposed",
                    "reviewing",
                    "voted",
                    "passed",
                    "rejected",
                    "alternative",
                    "withdrawn",
                    "promulgated",
                    "effective",
                    "unknown");

    public static String id(String value) {
        if (value == null || !value.matches("[A-Za-z0-9_-]{1,128}"))
            throw new IllegalArgumentException("invalid identifier");
        return value;
    }

    public void validate(Activity activity) {
        if (activity == null) throw new IllegalArgumentException("activity required");
        id(activity.id());
        id(activity.version());
        require(TYPES.contains(activity.type()), "unsupported activity type");
        require(STAGES.contains(activity.stage()), "unsupported stage");
        text(activity.title(), 500, "title");
        if (activity.summary() != null) text(activity.summary(), 5000, "summary");
        text(activity.coverage(), 2000, "coverage");
        require(
                activity.publishedAt() != null && activity.collectedAt() != null,
                "publication and collection times required");
        officialUrl(activity.sourceUrl());
        require(
                activity.personIds() != null && activity.personIds().size() <= 500,
                "invalid people");
        activity.personIds().forEach(TrackingPolicy::id);
        require(activity.topics() != null && activity.topics().size() <= 20, "invalid topics");
        activity.topics().forEach(TrackingPolicy::id);
        if (activity.billId() != null) id(activity.billId());
        require(
                activity.evidence() != null
                        && !activity.evidence().isEmpty()
                        && activity.evidence().size() <= 500,
                "specific evidence required");
        activity.evidence()
                .forEach(
                        item -> {
                            id(item.id());
                            officialUrl(item.sourceUrl());
                            text(item.locator(), 1000, "evidence locator");
                            text(item.sourceVersion(), 128, "source version");
                            if (item.excerpt() != null) text(item.excerpt(), 10000, "excerpt");
                        });
        require(activity.votes() != null && activity.votes().size() <= 500, "invalid votes");
        activity.votes()
                .forEach(
                        vote -> {
                            id(vote.personId());
                            id(vote.sessionId());
                            text(vote.name(), 100, "vote name");
                            require(
                                    VOTES.contains(vote.result()),
                                    "missing votes must remain unknown");
                            require(
                                    activity.personIds().contains(vote.personId()),
                                    "vote person missing from activity");
                        });
        require(
                activity.votes().stream()
                                .map(v -> v.sessionId() + ":" + v.personId())
                                .distinct()
                                .count()
                        == activity.votes().size(),
                "duplicate vote participant");
    }

    public static String officialUrl(String value) {
        try {
            URI uri = URI.create(value);
            String host = uri.getHost();
            require(
                    "https".equals(uri.getScheme())
                            && host != null
                            && uri.getUserInfo() == null
                            && (uri.getPort() == -1 || uri.getPort() == 443),
                    "official HTTPS source required");
            require(
                    host.equals("www.hscity.go.kr")
                            || host.equals("balance.go.kr")
                            || host.equals("www.balance.go.kr")
                            || HOSTS.stream().anyMatch(base -> host.equals(base) || host.endsWith("." + base)),
                    "unsupported source host");
            require(value.length() <= 2048 && uri.getRawFragment() == null, "invalid source URL");
            return value;
        } catch (NullPointerException ex) {
            throw new IllegalArgumentException("source URL required");
        }
    }

    static void text(String value, int maximum, String label) {
        require(value != null && !value.isBlank() && value.length() <= maximum, "invalid " + label);
    }

    static void require(boolean condition, String message) {
        if (!condition) throw new IllegalArgumentException(message);
    }
}
