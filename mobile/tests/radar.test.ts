import { expect, it } from "vitest";
import { readRadar } from "../src/radar";
it("뉴스 조회는 HTTPS에 한정하고 오류를 수집본으로 대체하지 않는다", async () => {
  let calls = 0;
  const request = async () => {
    calls++;
    return { status: 503, data: null };
  };
  expect((await readRadar("http://localhost:8080", request)).status).toBe(
    "error",
  );
  expect(calls).toBe(0);
  expect((await readRadar("https://records.example.org", request)).status).toBe(
    "error",
  );
  expect(
    (
      await readRadar("https://records.example.org", async () => ({
        status: 200,
        data: { items: [] },
      }))
    ).status,
  ).toBe("error");
  expect(
    (
      await readRadar("https://records.example.org", async () => ({
        status: 404,
        data: null,
      }))
    ).status,
  ).toBe("not-found");
});

import { sanitizeRoute } from "../src/navigation";
it("뉴스 목록과 상세 주소를 보존하고 임의 상세 경로는 거부한다", () => {
  expect(sanitizeRoute("radar")).toBe("radar");
  expect(sanitizeRoute("radar/news_0123456789abcdef")).toBe(
    "radar/news_0123456789abcdef",
  );
  expect(sanitizeRoute("radar/../../settings")).toBe("home");
});
