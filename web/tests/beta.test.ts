import { describe, expect, it } from "vitest";
import { isAllowedProxyPath } from "@/lib/api";
import { normalizeBetaSource, betaVisitKind, isBetaSession, sendBetaEvent } from "@/lib/beta";

describe("voluntary beta boundary", () => {
  it("normalizes only four aggregate acquisition sources without preserving campaign text", () => {
    expect(normalizeBetaSource(new URLSearchParams("utm_source=instagram&utm_campaign=private-issue"))).toBe("instagram");
    expect(normalizeBetaSource(new URLSearchParams("utm_source=unknown-politics"))).toBe("direct");
    expect(normalizeBetaSource(new URLSearchParams("utm_source=https://evil.test"))).toBe("direct");
    expect(betaVisitKind(new URLSearchParams("visit=research"))).toBe("research");
    expect(betaVisitKind(new URLSearchParams("visit=organic&issue=private"))).toBe("organic");
  });
  it("requires a real participating session and CSRF token", () => {
    expect(isBetaSession({ participating: false })).toBe(true);
    expect(isBetaSession({ participating: true })).toBe(false);
    expect(isBetaSession({ participating: true, csrfToken: "test-token" })).toBe(true);
    expect(isBetaSession({ participating: "yes" })).toBe(false);
  });
  it("never emits events before consent and strips context to generic depth and visit kind", async () => {
    const calls: { url: string; init?: RequestInit }[] = [];
    const fetcher = async (url: string | URL | Request, init?: RequestInit) => {
      calls.push({ url: String(url), init });
      return new Response(null, { status: 204 });
    };
    await sendBetaEvent({ participating: false }, "source_opened", "organic", fetcher as typeof fetch);
    expect(calls).toHaveLength(0);
    await sendBetaEvent({ participating: true, csrfToken: "csrf" }, "timeline_opened", "research", fetcher as typeof fetch);
    expect(calls).toHaveLength(1);
    expect(calls[0].url).toBe("/api/v1/beta/events");
    expect(JSON.parse(String(calls[0].init?.body))).toEqual({ event: "timeline_opened", visitKind: "research" });
    expect(new Headers(calls[0].init?.headers).get("x-csrf-token")).toBe("csrf");
  });
  it("allows exact public beta actions but never forwards researcher or admin reads", () => {
    expect(isAllowedProxyPath(["v1", "beta", "session"], "GET")).toBe(true);
    for (const action of ["participants", "events", "acquisition", "withdraw"])
      expect(isAllowedProxyPath(["v1", "beta", action], "POST")).toBe(true);
    expect(isAllowedProxyPath(["v1", "beta", "participants"], "GET")).toBe(false);
    expect(isAllowedProxyPath(["v1", "beta", "report"], "GET")).toBe(false);
    expect(isAllowedProxyPath(["v1", "beta", "session"], "POST")).toBe(false);
  });
});

describe("bounded same-tab research attribution", () => {
  it("survives reload without retaining any issue, actor or URL context", async () => {
    const { resolveBetaVisitKind, BETA_VISIT_CONTEXT_KEY } = await import("@/lib/beta");
    const storage = window.sessionStorage;
    storage.clear();
    const now = Date.parse("2026-10-17T10:00:00Z");
    expect(resolveBetaVisitKind(new URLSearchParams("visit=research&issue=private-actor&utm_campaign=private-topic"), storage, now)).toBe("research");
    const persisted = JSON.parse(storage.getItem(BETA_VISIT_CONTEXT_KEY)!);
    expect(persisted).toEqual({ visitKind: "research", until: now + 30 * 60 * 1000 });
    expect(Object.keys(persisted).sort()).toEqual(["until", "visitKind"]);
    expect(resolveBetaVisitKind(new URLSearchParams(), storage, now + 5 * 60 * 1000)).toBe("research");
    expect(JSON.stringify(persisted)).not.toContain("private");
  });
  it("expires on the next action after 30 minutes even without reloading the page", async () => {
    const { resolveBetaVisitKind, BETA_VISIT_CONTEXT_KEY } = await import("@/lib/beta");
    const storage = window.sessionStorage;
    storage.clear();
    const now = 1_000_000;
    expect(resolveBetaVisitKind(new URLSearchParams("visit=research"), storage, now)).toBe("research");
    expect(resolveBetaVisitKind(new URLSearchParams(), storage, now + 30 * 60 * 1000 - 1)).toBe("research");
    expect(resolveBetaVisitKind(new URLSearchParams(), storage, now + 30 * 60 * 1000)).toBe("organic");
    expect(storage.getItem(BETA_VISIT_CONTEXT_KEY)).toBeNull();
    expect(resolveBetaVisitKind(new URLSearchParams("visit=research"), storage, now + 31 * 60 * 1000)).toBe("research");
  });
  it("discards malformed or excessive stored context instead of trusting extra sensitive fields", async () => {
    const { resolveBetaVisitKind, BETA_VISIT_CONTEXT_KEY } = await import("@/lib/beta");
    const storage = window.sessionStorage;
    const now = 1_000_000;
    storage.setItem(BETA_VISIT_CONTEXT_KEY, JSON.stringify({ visitKind: "research", until: now + 60_000, issue: "private" }));
    expect(resolveBetaVisitKind(new URLSearchParams(), storage, now)).toBe("organic");
    expect(storage.getItem(BETA_VISIT_CONTEXT_KEY)).toBeNull();
  });
});
