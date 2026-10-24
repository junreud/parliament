import { describe, expect, it } from "vitest";
import { approvedMentions, readKnowledge } from "../src/people/api";
import { sanitizeRoute } from "../src/navigation";

describe("인물 공개 조회와 본문 연결", () => {
  it("Unicode 원문 범위가 맞는 승인 이름만 연결한다", () => {
    const text = "🙂 김하늘과 이서준";
    const a = {
      id: "m1",
      surface: "김하늘",
      start: 2,
      end: 5,
      personId: "p_a",
      decision: "approved" as const,
    };
    expect(approvedMentions(text, [a])).toEqual([a]);
    expect(approvedMentions(text, [{ ...a, decision: "pending" }])).toEqual([]);
    expect(approvedMentions(text, [{ ...a, surface: "다른사람" }])).toEqual([]);
    expect(approvedMentions(text, [a, { ...a, id: "m2", start: 3 }])).toEqual(
      [],
    );
  });
  it("HTTPS와 공개 경로만 사용한다", async () => {
    let called = false;
    const request = async () => {
      called = true;
      return { status: 200, data: {} };
    };
    expect(
      (
        await readKnowledge(
          "http://127.0.0.1:8080",
          "/api/v1/people/p_a/profile",
          request,
        )
      ).status,
    ).toBe("error");
    expect(
      (
        await readKnowledge(
          "https://records.example.org",
          "/admin/tracking",
          request,
        )
      ).status,
    ).toBe("error");
    expect(called).toBe(false);
  });
  it("다른 사람 프로필이나 후보 그래프를 거부한다", async () => {
    const profile = {
      id: "p_other",
      name: "다른 사람",
      kind: "person",
      facts: [],
      tenures: [],
      activities: [],
      relatedIssues: [],
    };
    expect(
      (
        await readKnowledge(
          "https://records.example.org",
          "/api/v1/people/p_a/profile",
          async () => ({ status: 200, data: profile }),
        )
      ).status,
    ).toBe("error");
    expect(
      (
        await readKnowledge(
          "https://records.example.org",
          "/api/v1/knowledge/graph?rootKind=person&rootId=p_a",
          async () => ({
            status: 200,
            data: { visibility: "candidate", nodes: [], edges: [] },
          }),
        )
      ).status,
    ).toBe("error");
  });
  it("실패·404를 미리보기로 대체하지 않는다", async () => {
    const path = "/api/v1/people/p_a/profile";
    expect(
      (
        await readKnowledge("https://records.example.org", path, async () => ({
          status: 503,
          data: {},
        }))
      ).status,
    ).toBe("error");
    expect(
      (
        await readKnowledge("https://records.example.org", path, async () => ({
          status: 404,
          data: {},
        }))
      ).status,
    ).toBe("not-found");
  });
  it("경로·인물 딥링크를 제한한다", () => {
    expect(sanitizeRoute("person/sample-haneul")).toBe("person/sample-haneul");
    expect(sanitizeRoute("person/../../admin")).toBe("home");
    expect(sanitizeRoute("https://evil.example")).toBe("home");
    expect(sanitizeRoute("people")).toBe("people");
  });
});
