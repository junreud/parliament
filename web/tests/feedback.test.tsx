import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ActivityFeedback } from "@/components/activity-feedback";
import { InterestsProvider } from "@/components/interests";
import { StrictMode } from "react";
afterEach(() => vi.unstubAllGlobals());
describe("first-party usefulness feedback", () => {
  it("sends only authenticated aggregate event and clicked rating with CSRF", async () => {
    const events: unknown[] = [];
    vi.stubGlobal("fetch", async (url: string, init?: RequestInit) => {
      if (url === "/api/v1/me") return Response.json({ authenticated: true, csrfToken: "csrf", follows: [{ kind: "person", targetId: "p1" }], frequency: "weekly" });
      expect(url).toBe("/api/v1/usage");
      expect(new Headers(init?.headers).get("X-CSRF-Token")).toBe("csrf");
      events.push(JSON.parse(String(init?.body)));
      return new Response(null, { status: 202 });
    });
    render(<InterestsProvider><ActivityFeedback activity={{ personIds: ["p1"], topics: [], billId: null }} /></InterestsProvider>);
    await waitFor(() => expect(screen.getByRole("button", { name: "도움이 되었어요" })).toBeInTheDocument());
    await waitFor(() => expect(events).toEqual([{ event: "activity_opened" }]));
    fireEvent.click(screen.getByRole("button", { name: "도움이 되었어요" }));
    await waitFor(() => expect(events).toEqual([{ event: "activity_opened" }, { event: "relevance", rating: true }]));
  });
  it("does not emit anonymous metrics or add identifying payload", async () => {
    const requests: string[] = [];
    vi.stubGlobal("fetch", async (url: string) => { requests.push(url); return Response.json({ authenticated: false }); });
    render(<InterestsProvider><ActivityFeedback activity={{ personIds: ["p1"], topics: [], billId: null }} /></InterestsProvider>);
    await waitFor(() => expect(requests).toEqual(["/api/v1/me"]));
    expect(screen.queryByText("이 내용이 관련 있고 이해하기 쉬웠나요?")).not.toBeInTheDocument();
  });

  it("records an authenticated related activity once after a delayed session and repeated effects", async () => {
    let resolveSession: (response: Response) => void = () => {};
    const session = new Promise<Response>(resolve => { resolveSession = resolve; });
    const events: unknown[] = [];
    vi.stubGlobal("fetch", async (url: string, init?: RequestInit) => {
      if (url === "/api/v1/me") return (await session).clone();
      expect(url).toBe("/api/v1/usage");
      expect(new Headers(init?.headers).get("X-CSRF-Token")).toBe("csrf");
      events.push(JSON.parse(String(init?.body)));
      return new Response(null, { status: 202 });
    });
    const view = render(<StrictMode><InterestsProvider><ActivityFeedback activity={{ personIds: ["p1"], topics: [], billId: null }} /></InterestsProvider></StrictMode>);
    expect(screen.queryByRole("button", { name: "도움이 되었어요" })).not.toBeInTheDocument();
    expect(events).toEqual([]);
    resolveSession(Response.json({ authenticated: true, csrfToken: "csrf", follows: [{ kind: "person", targetId: "p1" }], frequency: "weekly" }));
    await waitFor(() => expect(events).toEqual([{ event: "activity_opened" }]));
    view.rerender(<StrictMode><InterestsProvider><ActivityFeedback activity={{ personIds: ["p1"], topics: [], billId: null }} /></InterestsProvider></StrictMode>);
    fireEvent.click(screen.getByRole("button", { name: "도움이 되었어요" }));
    await waitFor(() => expect(events).toEqual([{ event: "activity_opened" }, { event: "relevance", rating: true }]));
  });
});


describe("related activity activation", () => {
  it.each([[false, ["housing"]], [true, ["housing", "rental-protection"]]])(
    "counts a followed issue only when its exact curated ID is present (%s)", async (matches, topics) => {
      const events: unknown[] = [];
      const requests: string[] = [];
      vi.stubGlobal("fetch", async (url: string, init?: RequestInit) => {
        requests.push(url);
        if (url === "/api/v1/me") return Response.json({ authenticated: true, csrfToken: "csrf", follows: [{ kind: "issue", targetId: "rental-protection" }], frequency: "weekly" });
        expect(url).toBe("/api/v1/usage");
        events.push(JSON.parse(String(init?.body)));
        return new Response(null, { status: 202 });
      });
      render(<InterestsProvider><ActivityFeedback activity={{ personIds: [], topics, billId: null }} /></InterestsProvider>);
      await waitFor(() => expect(screen.getByRole("button", { name: "도움이 되었어요" })).toBeInTheDocument());
      await waitFor(() => {
        expect(events).toEqual(matches ? [{ event: "activity_opened" }] : []);
        expect(requests).toEqual(matches ? ["/api/v1/me", "/api/v1/usage"] : ["/api/v1/me"]);
      });
    });

  it("does not count an unrelated detail as activation", async () => {
    const events: unknown[] = [];
    vi.stubGlobal("fetch", async (url: string, init?: RequestInit) => {
      if (url === "/api/v1/me") return Response.json({ authenticated: true, csrfToken: "csrf", follows: [{ kind: "person", targetId: "p1" }], frequency: "weekly" });
      events.push(JSON.parse(String(init?.body)));
      return new Response(null, { status: 202 });
    });
    render(<InterestsProvider><ActivityFeedback activity={{ personIds: ["unrelated"], topics: [], billId: null }} /></InterestsProvider>);
    await waitFor(() => expect(screen.getByRole("button", { name: "도움이 되었어요" })).toBeInTheDocument());
    expect(events).toEqual([]);
  });
});
