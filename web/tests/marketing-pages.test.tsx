import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MarketingStart } from "@/components/marketing-start";
import { BetaProvider } from "@/components/beta";
import type { EditorialIssue } from "@/lib/editorial";
const issue = { id: "amendment-process-20261017", title: "개헌의 절차", summary: "한 줄 요약", topic: "헌법", reviewStatus: "human-review-pending" } as EditorialIssue;
afterEach(() => vi.unstubAllGlobals());
describe("public marketing entry", () => {
  it("connects the media and app with exact issue links while visibly gating unreviewed promotion", () => {
    vi.stubGlobal("fetch", async () => new Response(null, { status: 503 }));
    render(<BetaProvider><MarketingStart issues={[issue]} /></BetaProvider>);
    expect(screen.getByRole("heading", { name: /흘려본 정치 뉴스/ })).toBeInTheDocument();
    expect(screen.getAllByText(/나라의 근황/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/의정의 흐름/).length).toBeGreaterThan(0);
    expect(screen.getByText(/사람의 최종 검토/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /개헌의 절차/ })).toHaveAttribute("href", "/issues/amendment-process-20261017");
    expect(screen.getByRole("link", { name: "베타 연구 참여 안내" })).toHaveAttribute("href", "/beta");
    expect(screen.queryByText(/알림을 보내/)).not.toBeInTheDocument();
  });
});


describe("marketing entry before publication", () => {
  it("shows a truthful preparing state rather than offering absent explanations", () => {
    vi.stubGlobal("fetch", async () => new Response(null, { status: 503 }));
    render(<BetaProvider><MarketingStart issues={[]} /></BetaProvider>);
    expect(screen.getByText("첫 해설을 준비하고 있습니다")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /이슈부터 읽어보기/ })).not.toBeInTheDocument();
    expect(screen.queryByText("설치·로그인 없이 읽을 수 있습니다")).not.toBeInTheDocument();
    expect(screen.getByText(/검토가 끝난 이슈부터/)).toBeInTheDocument();
  });
});
