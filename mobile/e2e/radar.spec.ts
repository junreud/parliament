import { test, expect } from "@playwright/test";
import snapshot from "./fixtures/radar.json" with { type: "json" };
import { mkdir } from "node:fs/promises";
const settings = {
  mode: "live",
  origin: "https://records.example.org",
  topics: [],
  saved: { preview: [], live: [] },
  fontSize: "normal",
  reducedMotion: true,
  haptics: false,
};
test("합성 뉴스 10건의 목록·원문·뒤로 가기 경로", async ({ page }) => {
  await page.addInitScript(
    (value) => localStorage.setItem("parliament.mobile.v1", JSON.stringify(value)),
    settings,
  );
  await page.route("https://records.example.org/**", (route) =>
    route.request().url().endsWith("/api/v1/radar")
      ? route.fulfill({ json: snapshot })
      : route.fulfill({ status: 200, json: { items: [], nextCursor: null } }),
  );
  await page.goto("/");
  await page.getByRole("button", { name: /뉴스에서 포착한 이슈 후보/ }).click();
  await expect(
    page.getByRole("heading", { name: "뉴스 이슈 후보" }),
  ).toBeVisible();
  await expect(page.locator(".radar-card")).toHaveCount(10);
  await page.locator(".radar-card").first().click();
  await expect(
    page.getByRole("heading", { name: "이슈 후보의 보도 근거" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "서로 다른 보도 읽기" }),
  ).toBeVisible();
  await expect(page.locator(".radar-source").first()).toHaveAttribute(
    "href",
    /^https:\/\/(www\.)?(yna|donga|hani|khan)\.co(m|\.kr)/,
  );
  await page.getByRole("button", { name: "뒤로" }).click();
  await expect(page.locator(".radar-card")).toHaveCount(10);
  await page.getByRole("button", { name: "뒤로" }).click();
  await expect(
    page.getByRole("heading", {
      name: /지금 어느 단계인지.*기록으로 확인하세요/,
      exact: true,
    }),
  ).toBeVisible();
});
for (const mode of ["ok", "empty", "error", "stale", "partial", "loading"]) {
  test(`뉴스 서버 ${mode} 상태를 구분한다`, async ({ page }) => {
    await mkdir("artifacts/radar", { recursive: true });
    await page.addInitScript(
      (v) => localStorage.setItem("parliament.mobile.v1", JSON.stringify(v)),
      settings,
    );
    await page.route("https://records.example.org/**", async (route) => {
      if (!route.request().url().endsWith("/api/v1/radar")) {
        await route.fulfill({
          status: 200,
          json: { items: [], nextCursor: null },
        });
        return;
      }
      if (mode === "loading") return;
      if (mode === "error") {
        await route.fulfill({ status: 503, json: { message: "offline" } });
        return;
      }
      const data = structuredClone(snapshot);
      if (mode === "empty") {
        data.items = [];
        data.shortfall = 10;
      }
      if (mode === "stale") {
        data.generatedAt = "2026-10-01T00:00:00Z";
        data.status = "unavailable";
      }
      if (mode === "partial") data.status = "partial";
      await route.fulfill({ status: 200, json: data });
    });
    await page.goto("/#radar");
    if (mode === "error")
      await expect(
        page.getByRole("heading", { name: "뉴스 후보를 불러오지 못했어요" }),
      ).toBeVisible();
    else if (mode === "empty")
      await expect(
        page.getByRole("heading", { name: "조건에 맞는 새 이슈가 없어요" }),
      ).toBeVisible();
    else if (mode === "loading")
      await expect(page.locator(".radar-notice[role=status]")).toHaveText(
        "뉴스 후보를 불러오는 중이에요.",
      );
    else {
      await expect(page.locator(".radar-card")).toHaveCount(10);
      if (mode === "stale")
        await expect(
          page.getByText(/최신 수집을 확인하지 못했어요/),
        ).toBeVisible();
      if (mode === "partial")
        await expect(
          page.getByText(/일부 출처 수집에 실패했어요/),
        ).toBeVisible();
    }
    if (mode === "error" || mode === "loading")
      await expect(page.locator(".radar-card")).toHaveCount(0);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await page.screenshot({
      path: `artifacts/radar/${mode}.png`,
      fullPage: false,
    });
  });
}
