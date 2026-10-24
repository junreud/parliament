import { describe, expect, it } from "vitest";
import { isActivity } from "@/lib/validation";
import { safeSource } from "@/lib/format";
import { parsePreferences } from "@/lib/preferences";
const item = { id: "event", type: "vote", title: "기록", summary: null, stage: "voted", personIds: [], topics: [], billId: null, occurredAt: null, publishedAt: "2026-10-01T00:00:00Z", collectedAt: "2026-10-01T00:00:00Z", sourceUrl: "https://www.assembly.go.kr/", evidence: [], votes: [], coverage: "공개 기록", corrected: false, version: "v1" };
describe("record truth contract", () => {
  it("does not allow truthy correction strings or malformed timestamps", () => {
    expect(isActivity(item)).toBe(true);
    expect(isActivity({ ...item, corrected: "false" })).toBe(false);
    expect(isActivity({ ...item, occurredAt: 123 })).toBe(false);
    expect(isActivity({ ...item, publishedAt: "not-a-date" })).toBe(false);
  });
  it("labels only official HTTPS sources as official links", () => {
    expect(safeSource("https://www.assembly.go.kr/record")).toBe("https://www.assembly.go.kr/record");
    expect(safeSource("https://assembly.go.kr.evil.example/record")).toBeNull();
    expect(safeSource("http://www.assembly.go.kr/record")).toBeNull();
    expect(safeSource("https://www.hscity.go.kr/mayor/index.do")).toBe("https://www.hscity.go.kr/mayor/index.do");
    expect(safeSource("https://evil.www.hscity.go.kr/x")).toBeNull();
    expect(safeSource("https://www.hscity.go.kr.evil.example/x")).toBeNull();
    expect(safeSource("https://www.balance.go.kr/base/board/read?boardNo=9778")).toBe("https://www.balance.go.kr/base/board/read?boardNo=9778");
    expect(safeSource("https://evil.www.balance.go.kr/x")).toBeNull();
    expect(safeSource("https://www.balance.go.kr.evil.example/x")).toBeNull();
  });
  it("drops IDs outside the backend identity contract", () => {
    expect(parsePreferences('{"follows":[{"kind":"person","targetId":"invalid:id"}]}').follows).toEqual([]);
  });
});
