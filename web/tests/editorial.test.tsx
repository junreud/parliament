import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { EditorialIssueView } from "@/components/editorial-issue";
import { BetaProvider } from "@/components/beta";
import { isReviewedEditorial, type EditorialIssue } from "@/lib/editorial";

const dossier: EditorialIssue = {
  id: "constitutional-procedure", title: "헌법에 넣자고 하면 바로 바뀔까?", question: "누가 어떤 절차로 헌법을 바꿀까요?",
  summary: "발언과 헌법 개정의 법적 절차는 구분해야 합니다.", topic: "헌법과 절차", currentStage: "공식 발언 확인", nextTrigger: "공식 발의 여부 확인",
  checkedAt: "2026-10-17T10:00:00+09:00", reviewStatus: "human-review-pending", background: ["배경 설명"], facts: ["확인한 절차"], claims: ["당사자의 주장"], unknowns: ["발의 여부"],
  timeline: [{ date: "2026-10-16", title: "공식 발언", detail: "발언 기록을 확인했습니다.", sourceIds: ["law"] }],
  sources: [{ id: "law", title: "대한민국헌법", publisher: "국가법령정보센터", url: "https://www.law.go.kr/법령/대한민국헌법", publishedAt: "1987-10-29", locator: "제128조부터 제130조", sourceType: "official-record", usageNote: "원문 링크로 확인" }], updates: [{ date: "2026-10-17", note: "초안 작성" }]
};
afterEach(() => vi.unstubAllGlobals());
describe("editorial readiness", () => {
  it("requires a dated human approval and never presents pending content as reviewed", () => {
    expect(isReviewedEditorial(dossier)).toBe(false);
    expect(isReviewedEditorial({ ...dossier, reviewStatus: "reviewed" })).toBe(false);
    expect(isReviewedEditorial({ ...dossier, reviewStatus: "reviewed", reviewedAt: "2026-10-18T10:00:00+09:00" })).toBe(true);
  });
  it("shows draft, evidence location and next trigger without requiring login or recording beta activation", async () => {
    const bodies: unknown[] = [];
    vi.stubGlobal("fetch", async (url: string, init?: RequestInit) => {
      if (url.endsWith("/session")) return Response.json({ participating: true, csrfToken: "csrf" });
      if (url.endsWith("/events")) bodies.push(JSON.parse(String(init?.body)));
      return new Response(null, { status: 204 });
    });
    render(<BetaProvider><EditorialIssueView issue={dossier} /></BetaProvider>);
    expect(screen.getByText("사람 검토 전 · 해설 초안")).toBeInTheDocument();
    expect(screen.getByText("제128조부터 제130조")).toBeInTheDocument();
    expect(screen.getByText("공식 발의 여부 확인")).toBeInTheDocument();
    expect(screen.queryByText("로그인이 필요합니다")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("link", { name: /대한민국헌법/ }));
    await waitFor(() => expect(screen.getByText("배경 설명")).toBeInTheDocument());
    expect(bodies).toEqual([]);
  });
  it("records only generic reviewed reading events after real consent", async () => {
    const bodies: unknown[] = [];
    vi.stubGlobal("fetch", async (url: string, init?: RequestInit) => {
      if (url.endsWith("/session")) return Response.json({ participating: true, csrfToken: "csrf" });
      if (url.endsWith("/events")) bodies.push(JSON.parse(String(init?.body)));
      return new Response(null, { status: 204 });
    });
    render(<BetaProvider><EditorialIssueView issue={{ ...dossier, reviewStatus: "reviewed", reviewedAt: "2026-10-18T10:00:00+09:00" }} /></BetaProvider>);
    await waitFor(() => expect(bodies).toContainEqual({ event: "explainer_opened", visitKind: "organic" }));
    fireEvent.click(screen.getByRole("link", { name: /대한민국헌법/ }));
    await waitFor(() => expect(bodies).toContainEqual({ event: "source_opened", visitKind: "organic" }));
    expect(JSON.stringify(bodies)).not.toContain(dossier.id);
    expect(JSON.stringify(bodies)).not.toContain("law.go.kr");
  });
});
