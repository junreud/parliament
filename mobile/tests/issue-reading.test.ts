import { readFileSync } from "node:fs";
import { describe, expect, it, vi } from "vitest";
import { readIssueReading } from "../src/issue-reading";

const sample = JSON.parse(
  readFileSync(
    new URL(
      "../../web/tests/fixtures/issue-reading-v1-success.json",
      import.meta.url,
    ),
    "utf8",
  ),
);
const origin = "https://records.example.org";

describe("공개 해설의 모바일 읽기", () => {
  it.each([
    [400, "invalid"],
    [404, "not-found"],
    [409, "conflict"],
    [503, "error"],
  ] as const)("HTTP %s를 %s로 구분한다", async (status, expected) => {
    expect(
      await readIssueReading(origin, "test-issue", async () => ({
        status,
        data: sample,
      })),
    ).toEqual({ status: expected });
  });

  it("같은 완전한 합성 계약을 정확한 HTTPS GET으로 읽고 매번 재조회한다", async () => {
    const request = vi.fn(async () => ({ status: 200, data: sample }));
    expect((await readIssueReading(origin, "test-issue", request)).status).toBe(
      "ok",
    );
    expect((await readIssueReading(origin, "test-issue", request)).status).toBe(
      "ok",
    );
    expect(request).toHaveBeenCalledTimes(2);
    expect(request).toHaveBeenCalledWith(
      `${origin}/api/v1/issues/test-issue/reading`,
    );
  });

  it("다른 origin·관리자·비공개 질의를 조합하지 않고 손상·대기 결과를 거부한다", async () => {
    const request = vi.fn(async () => ({ status: 200, data: sample }));
    for (const id of [
      "../admin",
      "test?visibility=pending",
      "https://other.test",
      "x".repeat(129),
    ])
      expect(await readIssueReading(origin, id, request)).toEqual({
        status: "invalid",
      });
    expect(
      await readIssueReading(
        "http://records.example.org",
        "test-issue",
        request,
      ),
    ).toEqual({ status: "error" });
    expect(request).not.toHaveBeenCalled();
    for (const data of [
      null,
      {},
      { ...sample, issueId: "different" },
      { ...sample, publicationState: "pending" },
    ])
      expect(
        await readIssueReading(origin, "test-issue", async () => ({
          status: 200,
          data,
        })),
      ).toEqual({ status: "error" });
    expect(
      await readIssueReading(origin, "test-issue", async () => {
        throw new Error("offline");
      }),
    ).toEqual({ status: "error" });
  });
});
