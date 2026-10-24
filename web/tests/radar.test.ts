import { describe, expect, it } from "vitest";
import { isRadarPage, radarSource, radarStale } from "../src/lib/radar";
const empty = {
  schemaVersion: 1,
  date: "2026-10-17",
  generatedAt: "2026-10-17T08:00:00Z",
  lastAttemptAt: "2026-10-17T08:00:00Z",
  runId: "run",
  status: "ok",
  selectionMethod: "rules-shortlist-human-review",
  baselineAvailable: false,
  items: [],
  sources: [],
  shortfall: 10,
  notice: "news metadata",
};
describe("뉴스 후보 계약", () => {
  it("성공한 빈 결과와 장애 상태를 구분한다", () => {
    expect(isRadarPage(empty)).toBe(true);
    expect(isRadarPage({ ...empty, status: "unavailable" })).toBe(true);
    expect(isRadarPage({ ...empty, status: "made-up" })).toBe(false);
  });
  it("무효 날짜·과다 항목·자의적 검증 완료를 거부한다", () => {
    expect(isRadarPage({ ...empty, generatedAt: "yesterday" })).toBe(false);
    expect(isRadarPage({ ...empty, date: "2026-02-30" })).toBe(false);
    expect(isRadarPage({ ...empty, items: Array(11).fill({}) })).toBe(false);
    expect(
      isRadarPage({
        ...empty,
        items: [{ title: "truth", reviewStatus: "verified" }],
      }),
    ).toBe(false);
  });
  it("매체별 HTTPS 출처와 오래된 시각을 검증한다", () => {
    expect(
      radarSource("https://www.yna.co.kr/view/A", "연합뉴스"),
    ).toBeTruthy();
    expect(radarSource("https://evil.example/A", "연합뉴스")).toBeNull();
    expect(
      radarSource("https://user:secret@www.yna.co.kr/view/A", "연합뉴스"),
    ).toBeNull();
    expect(radarSource("https://www.yna.co.kr/view/A", "경향신문")).toBeNull();
    expect(
      radarStale(empty.generatedAt, Date.parse("2026-10-17T15:00:00Z")),
    ).toBe(true);
  });
});
