import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ActivityCard } from "@/components/activity-card";
const activity = {
  id: "event-1", type: "announcement", title: "공식 발표 제목", summary: "기관이 계획을 발표했습니다.", stage: "announced",
  personIds: [], topics: ["housing"], billId: null, occurredAt: "2026-10-06T05:00:00Z",
  publishedAt: "2026-10-06T06:00:00Z", collectedAt: "2026-10-06T08:00:00Z", sourceUrl: "https://www.korea.kr/example",
  evidence: [{ id: "e1", sourceUrl: "https://www.korea.kr/example", excerpt: "공식 원문", locator: "본문 1", sourceVersion: "v1" }],
  votes: [], coverage: "무기명 표결 · 개인별 찬반 공개 없음", corrected: true, version: "v2"
};
describe("evidence based card", () => {
  it("marks announcement as an institutional claim and correction with source access", () => {
    render(<ActivityCard activity={activity} />);
    expect(screen.getByText("기관의 공식 발표 · 정책 효과는 별도 확인이 필요합니다.")).toBeInTheDocument();
    expect(screen.getByText("정정된 기록")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "원문 확인 ↗" })).toHaveAttribute("href", activity.sourceUrl);
  });
  it("never converts a secret ballot into a person's absence", () => {
    render(<ActivityCard activity={activity} />);
    expect(screen.getByText("무기명 표결 · 개인별 찬반 공개 없음")).toBeInTheDocument();
    expect(screen.queryByText("불참")).not.toBeInTheDocument();
  });
  it("omits unsafe source links", () => {
    render(<ActivityCard activity={{ ...activity, sourceUrl: "javascript:alert(1)" }} />);
    expect(screen.queryByRole("link", { name: "원문 확인 ↗" })).not.toBeInTheDocument();
  });
});
