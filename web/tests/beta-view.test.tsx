import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { BetaProvider, BetaForm } from "@/components/beta";
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); window.sessionStorage.clear(); window.history.replaceState(null, "", "/"); });

describe("beta research consent", () => {
  it("requires an unchecked explicit consent before submitting and never invents enrollment on failure", async () => {
    const calls: string[] = [];
    vi.stubGlobal("fetch", async (url: string) => {
      calls.push(url);
      return url.endsWith("/session") ? Response.json({ participating: false }) : new Response(null, { status: 503 });
    });
    render(<BetaProvider><BetaForm /></BetaProvider>);
    await waitFor(() => expect(screen.getByRole("button", { name: "베타 연구 참여 신청" })).not.toBeDisabled());
    expect(screen.getByRole("checkbox")).not.toBeChecked();
    fireEvent.change(screen.getByLabelText("이메일 주소"), { target: { value: "reader@example.test" } });
    fireEvent.click(screen.getByRole("button", { name: "베타 연구 참여 신청" }));
    expect(calls.filter(url => url.endsWith("/participants"))).toHaveLength(0);
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: "베타 연구 참여 신청" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("신청을 완료하지 못했습니다"));
    expect(screen.queryByText("베타 연구에 참여 중입니다")).not.toBeInTheDocument();
    expect(screen.getByText(/신청 후 35일 이내 삭제/)).toBeInTheDocument();
  });
  it("accepts only real backend success and supports explicit CSRF withdrawal", async () => {
    const requests: { url: string; body: unknown; csrf: string | null }[] = [];
    vi.stubGlobal("fetch", async (url: string, init?: RequestInit) => {
      if (url.endsWith("/session")) return Response.json({ participating: false });
      requests.push({ url, body: init?.body ? JSON.parse(String(init.body)) : null, csrf: new Headers(init?.headers).get("x-csrf-token") });
      if (url.endsWith("/participants")) return Response.json({ participating: true, csrfToken: "csrf" }, { status: 201 });
      return new Response(null, { status: 204 });
    });
    render(<BetaProvider><BetaForm /></BetaProvider>);
    await waitFor(() => expect(screen.getByRole("button", { name: "베타 연구 참여 신청" })).not.toBeDisabled());
    fireEvent.change(screen.getByLabelText("이메일 주소"), { target: { value: "reader@example.test" } });
    fireEvent.change(screen.getByLabelText("서비스를 알게 된 경로"), { target: { value: "instagram" } });
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: "베타 연구 참여 신청" }));
    await waitFor(() => expect(screen.getByText("베타 연구에 참여 중입니다")).toBeInTheDocument());
    expect(requests.find(request => request.url.endsWith("/participants"))?.body).toEqual({ email: "reader@example.test", consent: true, cohort: "external", source: "instagram" });
    fireEvent.click(screen.getByRole("button", { name: "연구 참여 철회 및 자료 삭제" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("철회"));
    expect(requests.at(-1)).toEqual({ url: "/api/v1/beta/withdraw", body: {}, csrf: "csrf" });
  });
  it("keeps reading open when the beta backend is unavailable", async () => {
    vi.stubGlobal("fetch", async () => new Response(null, { status: 503 }));
    render(<BetaProvider><BetaForm /></BetaProvider>);
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("참여 신청 서버"));
    expect(screen.getByRole("link", { name: "로그인 없이 이슈 읽기" })).toHaveAttribute("href", "/start");
    expect(screen.getByRole("button", { name: "베타 연구 참여 신청" })).toBeDisabled();
  });
});

describe("minimal beta acquisition and visit attribution", () => {
  it("sends only an allowlisted aggregate source and research visit kind, with no issue or campaign data", async () => {
    window.history.replaceState(null, "", "/issues/private-political-id?utm_source=instagram&utm_campaign=private-campaign&visit=research");
    const requests: { url: string; init?: RequestInit }[] = [];
    vi.stubGlobal("fetch", async (url: string, init?: RequestInit) => {
      requests.push({ url, init });
      if (url.endsWith("/session")) return Response.json({ participating: true, csrfToken: "csrf" });
      return new Response(null, { status: 204 });
    });
    const { BetaExplainerOpened } = await import("@/components/beta");
    render(<BetaProvider><BetaExplainerOpened eligible /></BetaProvider>);
    await waitFor(() => expect(requests.filter(request => request.url.endsWith("/events"))).toHaveLength(1));
    const acquisition = requests.find(request => request.url.endsWith("/acquisition"));
    expect(JSON.parse(String(acquisition?.init?.body))).toEqual({ source: "instagram" });
    expect(acquisition?.init?.credentials).toBe("omit");
    const event = requests.find(request => request.url.endsWith("/events"));
    expect(JSON.parse(String(event?.init?.body))).toEqual({ event: "explainer_opened", visitKind: "research" });
    expect(event?.init?.referrerPolicy).toBe("no-referrer");
    expect(JSON.stringify(requests)).not.toContain("private-political-id");
    expect(JSON.stringify(requests)).not.toContain("private-campaign");
  });
});

describe("beta timeline depth", () => {
  it("never records an anonymous expansion", async () => {
    const bodies: unknown[] = [];
    vi.stubGlobal("fetch", async (url: string, init?: RequestInit) => {
      if (url.endsWith("/session")) return Response.json({ participating: false });
      if (url.endsWith("/events")) bodies.push(JSON.parse(String(init?.body)));
      return new Response(null, { status: 204 });
    });
    const { BetaTimeline } = await import("@/components/beta");
    const { container } = render(<BetaProvider><BetaTimeline eligible><p>타임라인 기록</p></BetaTimeline></BetaProvider>);
    const details = container.querySelector("details")!;
    details.open = true;
    fireEvent(details, new Event("toggle", { bubbles: true }));
    expect(bodies).toEqual([]);
  });
});

describe("research attribution across page lifetimes", () => {
  it("persists a same-tab reload, then expires on a live-page depth action without sensitive storage", async () => {
    let now = Date.parse("2026-10-17T10:00:00Z");
    vi.spyOn(Date, "now").mockImplementation(() => now);
    window.history.replaceState(null, "", "/issues/first-private?visit=research&utm_campaign=private-topic");
    const bodies: unknown[] = [];
    vi.stubGlobal("fetch", async (url: string, init?: RequestInit) => {
      if (url.endsWith("/session")) return Response.json({ participating: true, csrfToken: "csrf" });
      if (url.endsWith("/events")) bodies.push(JSON.parse(String(init?.body)));
      return new Response(null, { status: 204 });
    });
    const { BetaExplainerOpened, BetaDepthLink } = await import("@/components/beta");
    const firstPage = render(<BetaProvider><BetaExplainerOpened eligible /></BetaProvider>);
    await waitFor(() => expect(bodies).toHaveLength(1));
    firstPage.unmount();
    now += 2 * 60 * 1000;
    window.history.replaceState(null, "", "/issues/second-private");
    render(<BetaProvider><BetaExplainerOpened eligible /><BetaDepthLink eligible href="#source">원문 열기</BetaDepthLink></BetaProvider>);
    await waitFor(() => expect(bodies).toHaveLength(2));
    expect(bodies).toEqual([
      { event: "explainer_opened", visitKind: "research" },
      { event: "explainer_opened", visitKind: "research" }
    ]);
    const { BETA_VISIT_CONTEXT_KEY } = await import("@/lib/beta");
    const context = JSON.parse(window.sessionStorage.getItem(BETA_VISIT_CONTEXT_KEY)!);
    expect(Object.keys(context).sort()).toEqual(["until", "visitKind"]);
    expect(JSON.stringify(context)).not.toContain("private");
    now += 29 * 60 * 1000;
    fireEvent.click(screen.getByRole("link", { name: "원문 열기" }));
    await waitFor(() => expect(bodies.at(-1)).toEqual({ event: "source_opened", visitKind: "organic" }));
    expect(window.sessionStorage.getItem(BETA_VISIT_CONTEXT_KEY)).toBeNull();
  });
});
