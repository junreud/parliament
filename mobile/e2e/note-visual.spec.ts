import { test, expect } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import { PREVIEW_RECORDS } from "../src/preview";
import { readFileSync } from "node:fs";
const laws = JSON.parse(
  readFileSync(new URL("../src/data/laws.json", import.meta.url), "utf8"),
);
const radar = JSON.parse(
  readFileSync(new URL("./fixtures/radar.json", import.meta.url), "utf8"),
);

// Synthetic record and fixed metadata. No external requests or political publication.
const record = {
  ...PREVIEW_RECORDS[0],
  id: "visual-note",
  title: "발표된 정책, 어떤 순서로 읽으면 될까요?",
  summary:
    "배경을 이해하고, 진행 단계와 원문을 차례로 확인하는 합성 검증 자료입니다.",
};
for (const viewport of [
  { name: "mobile", width: 412, height: 915 },
  { name: "desktop", width: 1440, height: 1000 },
]) {
  for (const state of ["default", "loading", "error", "empty"] as const) {
    test(`해설 노트 ${viewport.name} ${state}`, async ({ page }) => {
      await page.setViewportSize(viewport);
      await page.emulateMedia({ reducedMotion: "reduce" });
      await page.addInitScript(() =>
        localStorage.setItem(
          "parliament.mobile.v1",
          JSON.stringify({
            mode: "live",
            origin: "https://records.example.org",
            reducedMotion: true,
          }),
        ),
      );
      let release = () => {};
      const pending = new Promise<void>((resolve) => {
        release = resolve;
      });
      await page.route("https://records.example.org/**", async (route) => {
        const path = new URL(route.request().url()).pathname;
        if (path === "/api/v1/laws") return route.fulfill({ json: laws });
        if (path === "/api/v1/radar")
          return route.fulfill({
            json: { ...radar, generatedAt: "2026-10-17T00:00:00Z", items: [] },
          });
        if (state === "loading") await pending;
        if (state === "error" || state === "loading")
          return route.fulfill({ status: 503, body: "{}" });
        return route.fulfill({
          json: { items: state === "empty" ? [] : [record], nextCursor: null },
        });
      });
      await page.goto("/");
      if (state === "default")
        await expect(
          page.getByRole("heading", { name: record.title }),
        ).toBeVisible();
      if (state === "loading")
        await expect(
          page.getByRole("status", { name: "기록 불러오는 중" }),
        ).toBeVisible();
      if (state === "error")
        await expect(
          page.getByRole("heading", { name: "기록을 불러오지 못했어요" }),
        ).toBeVisible();
      if (state === "error" && viewport.name === "mobile") {
        const retry = await page
          .getByRole("button", { name: "다시 불러오기" })
          .boundingBox();
        const navigation = await page.locator(".bottom-nav").boundingBox();
        expect(retry).not.toBeNull();
        expect(navigation).not.toBeNull();
        expect(retry!.y + retry!.height).toBeLessThan(navigation!.y);
      }
      if (state === "empty")
        await expect(
          page.getByRole("heading", { name: "아직 공개된 기록이 없어요" }),
        ).toBeVisible();
      if (state !== "loading")
        await expect(
          page.getByRole("heading", { name: "법령 기본정보" }),
        ).toBeAttached();
      await page.evaluate(() => document.fonts.ready);
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBe(true);
      await mkdir("artifacts/note-visual", { recursive: true });
      await page.screenshot({
        path: `artifacts/note-visual/${viewport.name}-${state}.png`,
        animations: "disabled",
      });
      // Baselines must be reviewed in the same OS/browser/font environment first.
      if (process.env.PARLIAMENT_VISUAL_COMPARE === "1") {
        await expect(page).toHaveScreenshot(`${viewport.name}-${state}.png`, {
          animations: "disabled",
          maxDiffPixels: 0,
        });
      }
      release();
    });
  }
}
