import { describe, expect, it } from "vitest";
import { backendUrl, isAllowedProxyPath, readApi } from "@/lib/api";

describe("public API boundary", () => {
  it("allows only the contracted issue reading GET without opening adjacent private paths", () => {
    expect(isAllowedProxyPath(["v1", "issues", "test-issue", "reading"], "GET")).toBe(true);
    expect(backendUrl("/api/v1/issues/test-issue/reading", "http://localhost:8080").href).toBe("http://localhost:8080/api/v1/issues/test-issue/reading");
    for (const method of ["POST", "PUT", "DELETE"])
      expect(isAllowedProxyPath(["v1", "issues", "test-issue", "reading"], method)).toBe(false);
    for (const path of [["v1", "people", "test-person", "reading"], ["v1", "issues", "test-issue", "publications"], ["v1", "issues", "test-issue", "reading", "draft"]])
      expect(isAllowedProxyPath(path, "GET")).toBe(false);
  });
  it("uses a fixed backend origin and prevents path traversal or injected hosts", () => {
    expect(backendUrl("/api/v1/activities", "http://localhost:8080").href).toBe("http://localhost:8080/api/v1/activities");
    expect(() => backendUrl("https://evil.test/", "http://localhost:8080")).toThrow();
    expect(() => backendUrl("/api/v1/../admin", "http://localhost:8080")).toThrow();
    expect(isAllowedProxyPath(["admin", "ingestion"], "GET")).toBe(false);
    expect(isAllowedProxyPath(["v1", "activities", "event-1"], "GET")).toBe(true);
    expect(isAllowedProxyPath(["v1", "activities"], "POST")).toBe(false);
  });
  it("distinguishes unavailable API, missing records, and a valid empty response", async () => {
    expect(await readApi("/api/v1/activities", async () => new Response('{"items":[],"nextCursor":null}')))
      .toEqual({ status: "ok", data: { items: [], nextCursor: null } });
    expect(await readApi("/api/v1/activities/missing", async () => new Response("", { status: 404 })))
      .toEqual({ status: "not-found" });
    expect(await readApi("/api/v1/activities", async () => { throw new Error("offline"); }))
      .toEqual({ status: "offline" });
  });
  it("rejects malformed JSON rather than render fabricated records", async () => {
    expect(await readApi("/api/v1/activities", async () => new Response("oops"))).toEqual({ status: "offline" });
  });
});

describe("runtime response contracts", () => {
  it("rejects a malformed collection before a rendering crash", async () => {
    expect(await readApi("/api/v1/activities", async () => Response.json({ items: "not-an-array" }))).toEqual({ status: "offline" });
  });
  it("rejects an event without source and vote arrays", async () => {
    expect(await readApi("/api/v1/activities/id", async () => Response.json({ id: "id", title: "title" }))).toEqual({ status: "offline" });
  });
});

describe("strict record truth fields and history", () => {
  it("permits only published version history payloads under the additive public route", async () => {
    expect(isAllowedProxyPath(["v1", "activities", "event-1", "history"], "GET")).toBe(true);
    expect(await readApi("/api/v1/activities/event-1/history", async () => Response.json({ items: [{ version: "v1", reviewedAt: "2026-10-01T00:00:00Z", corrected: false, correctionReason: null }] }))).toEqual({ status: "ok", data: { items: [{ version: "v1", reviewedAt: "2026-10-01T00:00:00Z", corrected: false, correctionReason: null }] } });
  });
});
