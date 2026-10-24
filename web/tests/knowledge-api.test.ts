import { describe, expect, it } from "vitest";
import { isAllowedProxyPath, readApi } from "@/lib/api";
import { safeSource } from "@/lib/format";

const evidence = {
  id: "evidence-1", documentId: "document-1", documentVersion: "raw-v1",
  extractionVersion: "extract-v1", segmentId: "segment-1", start: 0, end: 3,
  excerpt: "김미애", before: "", after: "가 발의했다.", mentions: [],
  sourceUrl: "https://opinion.lawmaking.go.kr/record", title: "의안 원문"
};

describe("additive public knowledge API boundary", () => {
  it("allows the six read-only endpoints and rejects private review paths", () => {
    for (const path of [
      ["people", "person-1", "profile"], ["activities", "event-1", "context"],
      ["bills", "bill-1", "lineage"], ["issues", "issue-1", "timeline"],
      ["documents", "document-1"], ["evidence", "evidence-1"]
    ]) expect(isAllowedProxyPath(["v1", ...path], "GET")).toBe(true);
    expect(isAllowedProxyPath(["v1", "documents", "document-1"], "POST")).toBe(false);
    expect(isAllowedProxyPath(["v1", "knowledge", "review"], "GET")).toBe(false);
    expect(isAllowedProxyPath(["v1", "people", "x".repeat(129), "profile"], "GET")).toBe(false);
    expect(isAllowedProxyPath(["v1", "documents", "invalid:id"], "GET")).toBe(false);
  });

  it("accepts version-pinned evidence but rejects invalid offsets and unrecognized decisions", async () => {
    const path = "/api/v1/evidence/evidence-1";
    expect((await readApi(path, async () => Response.json(evidence))).status).toBe("ok");
    expect((await readApi(path, async () => Response.json({ ...evidence, end: -1 }))).status).toBe("offline");
    expect((await readApi(path, async () => Response.json({ ...evidence, mentions: [{ id: "mention-1", start: 0, end: 3, surface: "김미애", personId: "person-1", decision: "public" }] }))).status).toBe("offline");
  });

  it("does not treat an unavailable context as an empty successful record", async () => {
    const path = "/api/v1/activities/event-1/context?version=v1";
    expect(await readApi(path, async () => new Response("", { status: 404 }))).toEqual({ status: "not-found" });
    expect(await readApi(path, async () => new Response("", { status: 500 }))).toEqual({ status: "offline" });
    expect((await readApi(path, async () => Response.json({ eventId: "event-1", eventVersion: "v1" }))).status).toBe("offline");
  });

  it("recognizes official ministry, library and legislation links without trusting lookalike hosts", () => {
    for (const host of ["www.mogef.go.kr", "ampos.nanet.go.kr", "opinion.lawmaking.go.kr"])
      expect(safeSource(`https://${host}/record`)).toBe(`https://${host}/record`);
    expect(safeSource("https://nanet.go.kr.attacker.example/record")).toBeNull();
    expect(safeSource("https://www.mogef.go.kr@attacker.example/record")).toBeNull();
  });
});

describe("knowledge publication contract", () => {
  const document = {
    id: "document-1", version: "raw-v1", extractionVersion: "extract-v1", sourceKey: "official", recordKey: "record-1",
    sourceUrl: "https://ampos.nanet.go.kr/record", title: "공식 문서", format: "html", bodyStatus: "available", licenseStatus: "allowed",
    publishedAt: "2024-07-12", collectedAt: "2026-10-08T00:00:00Z", datePrecision: "date",
    segments: [{ id: "segment-1", text: "🙂김미애", locator: "본문 1", mentions: [{ id: "mention-1", surface: "김미애", start: 1, end: 4, personId: "person-1", decision: "approved" }] }]
  };
  const activity = { id: "event-1", type: "bill", title: "발의 기록", summary: null, stage: "proposed", personIds: ["person-1"], topics: [], billId: "bill-1", occurredAt: null, publishedAt: "2024-07-12T00:00:00Z", collectedAt: "2026-10-08T00:00:00Z", sourceUrl: document.sourceUrl, evidence: [], votes: [], coverage: "확인된 기록", corrected: false, version: "v1" };
  const context = { eventId: "event-1", eventVersion: "v1", changeKind: "new_record", activity, participants: [{ personId: "person-1", name: "김미애", role: "lead_sponsor", evidenceIds: [evidence.id], organizationAtTime: null, positionAtTime: "의원" }], relations: [], evidence: [evidence], documents: [document] };

  it("accepts reviewed source segments with date precision while refusing storage paths and unlicensed text", async () => {
    const path = "/api/v1/documents/document-1?version=raw-v1";
    expect((await readApi(path, async () => Response.json(document))).status).toBe("ok");
    expect((await readApi(path, async () => Response.json({ ...document, rawStorageKey: "private/path" }))).status).toBe("offline");
    expect((await readApi(path, async () => Response.json({ ...document, licenseStatus: "unknown" }))).status).toBe("offline");
    expect((await readApi(path, async () => Response.json({ ...document, segments: [{ ...document.segments[0], mentions: [{ ...document.segments[0].mentions[0], start: 0 }] }] }))).status).toBe("offline");
  });

  it("accepts additive contexts and profile histories only when the legacy Activity version agrees", async () => {
    expect((await readApi("/api/v1/activities/event-1/context", async () => Response.json(context))).status).toBe("ok");
    expect((await readApi("/api/v1/activities/event-1/context", async () => Response.json({ ...context, eventVersion: "wrong-version" }))).status).toBe("offline");
    const profile = { id: "person-1", name: "김미애", kind: "person", facts: [{ label: "이름", value: "김미애", evidenceIds: [evidence.id] }], tenures: [], relatedIssues: [{ id: "issue-1", title: "양육비" }], activities: [context] };
    expect((await readApi("/api/v1/people/person-1/profile", async () => Response.json(profile))).status).toBe("ok");
    expect((await readApi("/api/v1/issues/issue-1/timeline", async () => Response.json({ id: "issue-1", items: [context], nextCursor: "cursor-1" }))).status).toBe("ok");
  });

  it("does not expose pending bill relationships", async () => {
    const relation = { id: "relation-1", subjectId: "bill-1", objectId: "bill-2", type: "incorporated_into_alternative", decision: "pending", reason: "검수 중", evidenceIds: [evidence.id] };
    expect((await readApi("/api/v1/bills/bill-1/lineage", async () => Response.json({ id: "bill-1", items: [relation] }))).status).toBe("offline");
  });

  it("refuses a document or context returned at a different requested immutable version", async () => {
    expect((await readApi("/api/v1/documents/document-1?version=raw-v2", async () => Response.json(document))).status).toBe("offline");
    expect((await readApi("/api/v1/documents/document-1?version=raw-v1&extractionVersion=extract-v2", async () => Response.json(document))).status).toBe("offline");
    expect((await readApi("/api/v1/activities/event-1/context?version=v2", async () => Response.json(context))).status).toBe("offline");
  });
});
