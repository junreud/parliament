import { describe, expect, it, vi } from "vitest";
import sample from "./fixtures/issue-reading-v1-success.json";
import { isIssueReading } from "@/lib/issue-reading";
import { readIssueReading } from "@/lib/issue-reading-api";

// Exact output of the backend IssueReadingTest; never a public political record.
const fixture = () => structuredClone(sample);

describe("versioned public issue reading contract", () => {
  it("accepts the complete Java synthetic response with its role context", () => {
    expect(isIssueReading("test-issue", fixture())).toBe(true);
  });

  it.each(["pending", "draft", "rejected", "withdrawn"])("refuses %s as a published bundle", state => {
    expect(isIssueReading("test-issue", { ...fixture(), publicationState: state })).toBe(false);
  });

  it.each([
    ["missing context", (v: ReturnType<typeof fixture>) => { v.contexts = []; }],
    ["missing role", (v: ReturnType<typeof fixture>) => { v.contexts[0].relations = []; }],
    ["missing participant", (v: ReturnType<typeof fixture>) => { v.contexts[0].participants = []; }],
    ["wrong source version", (v: ReturnType<typeof fixture>) => { v.evidence[0].documentVersion = "different-version"; }],
    ["unknown evidence", (v: ReturnType<typeof fixture>) => { v.blocks[0].evidenceIds = ["missing"]; }],
    ["unknown person", (v: ReturnType<typeof fixture>) => { v.blocks[0].personIds = ["missing"]; }],
    ["missing fact evidence", (v: ReturnType<typeof fixture>) => { v.blocks[1].evidenceIds = []; }],
    ["duplicate paragraph", (v: ReturnType<typeof fixture>) => { v.blocks.push(v.blocks[0]); }],
    ["partial bundle", (v: ReturnType<typeof fixture>) => { v.evidence = []; }],
  ] as const)("refuses %s without weakening existing context validation", (_label, change) => {
    const value = fixture();
    change(value);
    expect(isIssueReading("test-issue", value)).toBe(false);
  });

  it("rejects a different issue and malformed or oversized payloads", () => {
    expect(isIssueReading("other-issue", fixture())).toBe(false);
    for (const value of [null, [], {}, { ...fixture(), blocks: Array(201).fill(fixture().blocks[0]) }])
      expect(isIssueReading("test-issue", value)).toBe(false);
  });

  it("rejects contradictory private markers at the bundle, paragraph and participant", () => {
    const value = fixture();
    for (const other of [
      { ...value, visibility: "candidate" },
      { ...value, blocks: value.blocks.map(b => ({ ...b, decision: "pending" })) },
      { ...value, contexts: value.contexts.map(c => ({ ...c, participants: c.participants.map(p => ({ ...p, visibility: "candidate" })) })) },
    ]) expect(isIssueReading("test-issue", other)).toBe(false);
  });

  it("rejects numeric dates and invalid change dates while preserving an unknown optional change time", () => {
    const value = fixture();
    const activity: Record<string, unknown> = value.contexts[0].activity;
    activity.publishedAt = 1792195200;
    expect(isIssueReading("test-issue", value)).toBe(false);
    activity.publishedAt = "2026-10-17T00:00:00Z";
    activity.changedAt = "not-a-date";
    expect(isIssueReading("test-issue", value)).toBe(false);
    activity.changedAt = null;
    expect(isIssueReading("test-issue", value)).toBe(true);
    expect(activity.changedAt).toBeNull();
  });

  it("rejects a non-versioned publication identifier", () => {
    expect(isIssueReading("test-issue", { ...fixture(), version: "copied-old-version" })).toBe(false);
  });
});

describe("web issue reading GET", () => {
  it.each([[400, "invalid"], [404, "not-found"], [409, "conflict"], [503, "error"], [500, "error"]] as const)("keeps HTTP %s distinct without returning a body", async (status, expected) => {
    const result = await readIssueReading("test-issue", async () => Response.json({ summary: "private-error-body" }, { status }));
    expect(result).toEqual({ status: expected });
  });

  it("uses the fixed backend, GET, no-store and no credentials", async () => {
    const fetcher = vi.fn(async () => Response.json(fixture()));
    expect((await readIssueReading("test-issue", fetcher)).status).toBe("ok");
    expect(fetcher.mock.calls[0]).toEqual([
      expect.stringMatching(/^https?:\/\/[^/]+\/api\/v1\/issues\/test-issue\/reading$/),
      expect.objectContaining({ method: "GET", cache: "no-store", credentials: "omit", redirect: "error" }),
    ]);
  });

  it("does not fetch invalid IDs or accept private, malformed or failed responses", async () => {
    const fetcher = vi.fn(async () => Response.json(fixture()));
    for (const id of ["../admin", "test?state=draft", "https://other.test", "x".repeat(129)])
      expect(await readIssueReading(id, fetcher)).toEqual({ status: "invalid" });
    expect(fetcher).not.toHaveBeenCalled();
    expect(await readIssueReading("test-issue", async () => { throw new Error("offline"); })).toEqual({ status: "error" });
    expect(await readIssueReading("test-issue", async () => new Response("not-json"))).toEqual({ status: "error" });
    expect(await readIssueReading("test-issue", async () => Response.json({ ...fixture(), publicationState: "pending" }))).toEqual({ status: "error" });
  });
});
