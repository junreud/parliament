import { describe, expect, it } from "vitest";
import { loadRelatedBillSummaries } from "@/lib/bill-lineage";
import type { KnowledgeRelation } from "@/lib/knowledge-contracts";

function relation(index: number, otherId: string): KnowledgeRelation {
  return { id: `relation-${index}`, subjectId: "current-bill", objectId: otherId, type: "incorporated_into_alternative", decision: "approved", reason: "근거 확인", evidenceIds: ["evidence-1"] };
}

describe("bounded related bill summaries", () => {
  it("deduplicates IDs, queries at most twenty summaries, and uses at most four concurrent lookups", async () => {
    const requested: string[] = [];
    let concurrent = 0;
    let peak = 0;
    const items = Array.from({ length: 32 }, (_, index) => relation(index, `bill-${index}`));
    items.splice(1, 0, relation(40, "bill-0"));
    const summaries = await loadRelatedBillSummaries("current-bill", items, async id => {
      requested.push(id);
      concurrent += 1;
      peak = Math.max(peak, concurrent);
      await Promise.resolve();
      concurrent -= 1;
      return { status: "ok", data: { id, title: `법안 ${id}`, stage: "unknown" } };
    });
    expect(requested).toEqual(Array.from({ length: 20 }, (_, index) => `bill-${index}`));
    expect(peak).toBeGreaterThan(1);
    expect(peak).toBeLessThanOrEqual(4);
    expect(Object.keys(summaries)).toHaveLength(20);
    expect(summaries["bill-20"]).toBeUndefined();
  });

  it("preserves missing and failed lookups without borrowing the current bill's stage", async () => {
    const summaries = await loadRelatedBillSummaries("current-bill", [relation(1, "missing"), relation(2, "failed")], async id => {
      if (id === "missing") return { status: "not-found" };
      throw new Error("unavailable");
    });
    expect(summaries).toEqual({ missing: { status: "not-found" }, failed: { status: "offline" } });
  });

  it("queries originals when viewing their shared alternative and excludes unrelated relationships", async () => {
    const requested: string[] = [];
    const items = [{ ...relation(1, "current-bill"), subjectId: "original-1" }, { ...relation(2, "other-bill"), subjectId: "unrelated-bill" }];
    await loadRelatedBillSummaries("current-bill", items, async id => {
      requested.push(id);
      return { status: "ok", data: { title: "원안", stage: "alternative" } };
    });
    expect(requested).toEqual(["original-1"]);
  });
});
