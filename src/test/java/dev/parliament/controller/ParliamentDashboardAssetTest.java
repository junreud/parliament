package dev.parliament.controller;

import org.junit.jupiter.api.Test;

import java.nio.charset.StandardCharsets;

import static org.assertj.core.api.Assertions.assertThat;

class ParliamentDashboardAssetTest {

    @Test
    void dashboardIsSelfContainedAndExplainsOperationalStates() throws Exception {
        String html = resource("/static/dashboard/index.html");
        String styles = resource("/static/dashboard/dashboard.css");
        String script = resource("/static/dashboard/dashboard.js");

        assertThat(html).contains("국회 데이터 적재 현황", "오늘 예정", "일별 적재 추이", "API별 상세");
        assertThat(script).contains(
                "SUCCESS_CHANGED", "SUCCESS_UNCHANGED", "SUCCESS_EMPTY",
                "SKIPPED_NO_PARENT_CHANGES", "RETRY_EXHAUSTED", "FAILED", "MISSED");
        assertThat(script).doesNotContain("localStorage", "sessionStorage", "http://", "https://");
        assertThat(styles).contains("[hidden] { display: none !important; }");
    }

    private String resource(String path) throws Exception {
        try (var input = getClass().getResourceAsStream(path)) {
            assertThat(input).isNotNull();
            return new String(input.readAllBytes(), StandardCharsets.UTF_8);
        }
    }
}
