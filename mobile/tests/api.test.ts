import { describe, expect, it } from "vitest";
import { readRecords } from "../src/api";
describe("공개 기록 조회", () => {
  it("장애를 빈 기록으로 바꾸지 않는다", async () => {
    const result = await readRecords(
      "https://records.example.org",
      "/api/v1/activities",
      async () => ({ status: 503, data: { items: [] } }),
    );
    expect(result.status).toBe("error");
  });
  it("실제 빈 결과를 유지한다", async () => {
    const result = await readRecords(
      "https://records.example.org",
      "/api/v1/activities",
      async () => ({ status: 200, data: { items: [], nextCursor: null } }),
    );
    expect(result).toEqual({
      status: "ok",
      data: { items: [], nextCursor: null },
    });
  });
  it("404를 별도로 표시한다", async () =>
    expect(
      (
        await readRecords(
          "https://records.example.org",
          "/api/v1/activities",
          async () => ({ status: 404, data: {} }),
        )
      ).status,
    ).toBe("not-found"));
  it("200 응답의 손상된 자료를 거부한다", async () =>
    expect(
      (
        await readRecords(
          "https://records.example.org",
          "/api/v1/activities",
          async () => ({ status: 200, data: { items: [{ title: "가짜" }] } }),
        )
      ).status,
    ).toBe("error"));
  it("관리 API로 요청하지 않는다", async () => {
    let called = false;
    const result = await readRecords(
      "https://records.example.org",
      "/api/v1/admin",
      async () => {
        called = true;
        return { status: 200, data: { items: [] } };
      },
    );
    expect(result.status).toBe("error");
    expect(called).toBe(false);
  });
  it("잘못된 서버로 요청하지 않는다", async () => {
    let called = false;
    await readRecords(
      "http://records.example.org",
      "/api/v1/activities",
      async () => {
        called = true;
        return { status: 200, data: { items: [] } };
      },
    );
    expect(called).toBe(false);
  });
  it("네트워크 예외를 오류로 반환한다", async () =>
    expect(
      (
        await readRecords(
          "https://records.example.org",
          "/api/v1/activities",
          async () => {
            throw new Error("offline");
          },
        )
      ).status,
    ).toBe("error"));
});
