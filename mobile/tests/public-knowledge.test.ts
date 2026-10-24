import { describe, expect, it } from "vitest";
import { readKnowledge } from "../src/people/api";
import { sanitizeRoute } from "../src/navigation";

const origin = "https://records.example.org";
const relation = {
  id: "relation_1",
  subjectId: "bill_original",
  objectId: "bill_alternative",
  type: "incorporated_into_alternative",
  evidenceIds: ["ev_1"],
  decision: "approved",
  reason: "합성 검증 자료",
};
const lineage = { id: "bill_original", items: [relation] };

describe("모바일 승인 법안 공개 읽기 경계", () => {
  it("승인된 원안·대안과 공개 법안만 읽는다", async () => {
    expect(
      await readKnowledge(
        origin,
        "/api/v1/bills/bill_original/lineage",
        async () => ({ status: 200, data: lineage }),
      ),
    ).toEqual({ status: "ok", data: lineage });
    const bill = {
      id: "bill_original",
      title: "검증용 원안",
      stage: "unknown",
      activities: [],
      votes: [],
      sourceUrl: null,
    };
    expect(
      await readKnowledge(origin, "/api/v1/bills/bill_original", async () => ({
        status: 200,
        data: bill,
      })),
    ).toEqual({ status: "ok", data: bill });
    expect(sanitizeRoute("bill/bill_original")).toBe("bill/bill_original");
    expect(sanitizeRoute("bill/../../admin")).toBe("home");
  });
  it.each([
    { ...lineage, id: "other_bill" },
    { ...lineage, items: [{ ...relation, decision: "pending" }] },
    { ...lineage, items: [{ ...relation, evidenceIds: [] }] },
    {
      ...lineage,
      items: [
        { ...relation, subjectId: "unrelated", objectId: "also_unrelated" },
      ],
    },
    { ...lineage, items: [{ ...relation, type: "concerns" }] },
  ])(
    "대기·근거 없음·다른 법안의 관계를 공개 결과로 받지 않는다",
    async (data) => {
      expect(
        (
          await readKnowledge(
            origin,
            "/api/v1/bills/bill_original/lineage",
            async () => ({ status: 200, data }),
          )
        ).status,
      ).toBe("error");
    },
  );
  it("명시적인 비공개 프로필과 직위 주장을 거부한다", async () => {
    const profile = {
      id: "p_1",
      name: "합성 인물",
      kind: "person",
      facts: [],
      tenures: [],
      relatedIssues: [],
      activities: [],
      visibility: "candidate",
    };
    expect(
      (
        await readKnowledge(origin, "/api/v1/people/p_1/profile", async () => ({
          status: 200,
          data: profile,
        }))
      ).status,
    ).toBe("error");
  });
  it("관리자·비공개 파일·다른 origin을 요청하지 않는다", async () => {
    let calls = 0;
    for (const path of [
      "/admin/knowledge/batches",
      "/private/candidates.sqlite",
      "https://other.example/api/v1/people/p_1/profile",
    ]) {
      await readKnowledge(origin, path, async () => {
        calls++;
        return { status: 200, data: {} };
      });
    }
    expect(calls).toBe(0);
  });
});
