import { describe, expect, it } from "vitest";
import { isAllowedProxyPath, readApi } from "../src/lib/api";
import { isApiPayload } from "../src/lib/validation";
import { forwardApi } from "../src/lib/proxy";
import snapshot from "../../mobile/src/data/laws.json";

describe("공개 법령 읽기 전용 프록시", () => {
  it("허용된 컬렉션 GET만 전달한다", () => {
    expect(isAllowedProxyPath(["v1", "laws"], "GET")).toBe(true);
    expect(isAllowedProxyPath(["v1", "laws"], "POST")).toBe(false);
    expect(isAllowedProxyPath(["v1", "laws", "review"], "GET")).toBe(false);
  });
  it("실제 공개 내보내기 계약과 출처를 검증한다", () => {
    expect(isApiPayload("/api/v1/laws", snapshot)).toBe(true);
    expect(
      isApiPayload("/api/v1/laws", { items: [{ id: "a", title: "fake" }] }),
    ).toBe(false);
    expect(
      isApiPayload("/api/v1/laws", {
        ...snapshot,
        items: [
          {
            ...snapshot.items[0],
            sourceUrl: snapshot.items[0].sourceUrl + "&OC=private",
          },
        ],
      }),
    ).toBe(false);
  });
  it("백엔드 관리자 키를 전달하지 않는다", async () => {
    let headers: Headers | undefined;
    const response = await forwardApi(
      new Request("https://app.example/api/v1/laws", {
        headers: { "X-Parliament-Ingestion-Key": "fixture-only" },
      }),
      ["v1", "laws"],
      async (_url, init) => {
        headers = new Headers(init?.headers);
        return Response.json(snapshot);
      },
    );
    expect(response.status).toBe(200);
    expect(headers?.has("X-Parliament-Ingestion-Key")).toBe(false);
    expect(await response.json()).toEqual(snapshot);
  });
  it("손상된 성공 응답을 정상 목록으로 취급하지 않는다", async () => {
    expect(
      await readApi("/api/v1/laws", async () =>
        Response.json({ items: [{ title: "fake" }] }),
      ),
    ).toEqual({ status: "offline" });
  });
});
