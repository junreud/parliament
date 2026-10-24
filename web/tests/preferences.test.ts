import { describe, expect, it } from "vitest";
import { parsePreferences, toggleFollow, matchesFollows } from "@/lib/preferences";

describe("anonymous interests", () => {
  it("never restores tokens or invalid interest data from local storage", () => {
    expect(parsePreferences('{"token":"secret","frequency":"daily","follows":[{"kind":"person","targetId":"p1"},{"kind":"admin","targetId":"x"}]}'))
      .toEqual({ follows: [{ kind: "person", targetId: "p1" }], frequency: "daily" });
    expect(parsePreferences("bad-json")).toEqual({ follows: [], frequency: "weekly" });
  });
  it("toggles a follow without duplicates", () => {
    const added = toggleFollow([], { kind: "person", targetId: "p1" });
    expect(added).toEqual([{ kind: "person", targetId: "p1" }]);
    expect(toggleFollow(added, { kind: "person", targetId: "p1" })).toEqual([]);
  });
  it("matches interests by IDs and topics rather than name guesses", () => {
    const record = { personIds: ["p1"], topics: ["housing"], billId: "b1" };
    expect(matchesFollows(record, [{ kind: "person", targetId: "p1" }])).toBe(true);
    expect(matchesFollows(record, [{ kind: "topic", targetId: "labor" }])).toBe(false);
    expect(matchesFollows(record, [{ kind: "issue", targetId: "rental-protection" }])).toBe(false);
    expect(matchesFollows({ ...record, topics: ["housing", "rental-protection"] },
      [{ kind: "issue", targetId: "rental-protection" }])).toBe(true);
  });
});
