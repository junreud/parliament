import { describe, expect, it } from "vitest";
import { loadFollowFeed } from "@/lib/feed";
const item = { id: "event-1", type: "bill", title: "기록", summary: "", stage: "proposed", personIds: ["p1"], topics: ["housing"], billId: "b1", occurredAt: null, publishedAt: "2026-10-01T00:00:00Z", collectedAt: "2026-10-01T01:00:00Z", sourceUrl: "https://example.test/", evidence: [], votes: [], coverage: "공개 기록", corrected: false, version: "1" };
describe("bounded personalized feed", () => {
  it("queries each target and merges duplicate events without dropping unrelated pages", async () => {
    const paths: string[] = [];
    const result = await loadFollowFeed([{ kind: "person", targetId: "p1" }, { kind: "topic", targetId: "housing" }], async input => {
      paths.push(String(input));
      return Response.json({ items: [item], nextCursor: "older" });
    });
    expect(paths).toContain("/api/v1/activities?personId=p1&limit=20");
    expect(paths).toContain("/api/v1/activities?topic=housing&limit=20");
    expect(result.items).toHaveLength(1);
    expect(result.status).toBe("ok");
  });
  it("distinguishes a partial source failure from an empty interest feed", async () => {
    const result = await loadFollowFeed([{ kind: "person", targetId: "p1" }, { kind: "issue", targetId: "housing-1" }], async input => {
      return String(input).includes("issues") ? new Response("", { status: 503 }) : Response.json({ items: [item] });
    });
    expect(result.status).toBe("partial");
    expect(result.items).toHaveLength(1);
  });
});

describe("precise publication chronology", () => {
  it("orders review times chronologically when ISO fractional precision differs", async () => {
    const result = await loadFollowFeed([{ kind: "person", targetId: "p1" }], async () => Response.json({ items: [
      { ...item, id: "older", changedAt: "2026-10-01T00:00:00.340Z" },
      { ...item, id: "newer", changedAt: "2026-10-01T00:00:00.340001Z" }
    ] }));
    expect(result.items.map(activity => activity.id)).toEqual(["newer", "older"]);
  });
});
