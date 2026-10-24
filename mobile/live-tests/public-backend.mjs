import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import { mkdir, writeFile } from "node:fs/promises";
import { chromium } from "playwright";

const origin = new URL(process.env.PARLIAMENT_PUBLIC_API_ORIGIN || "");
assert.ok(
  origin.protocol === "https:" &&
    !origin.username &&
    !origin.password &&
    origin.pathname === "/" &&
    !origin.search &&
    !origin.hash,
);
const output = new URL("../artifacts/public-live/", import.meta.url);
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true });
const report = {
  origin: origin.origin,
  intercepted: false,
  checks: [],
  responses: [],
  pageErrors: [],
};
try {
  for (const width of [360, 412]) {
    const context = await browser.newContext({
      viewport: { width, height: 915 },
      isMobile: true,
      hasTouch: true,
    });
    const page = await context.newPage();
    page.on("pageerror", (error) => report.pageErrors.push(error.message));
    page.on("response", (response) => {
      const url = new URL(response.url());
      if (url.origin === origin.origin)
        report.responses.push({
          path: url.pathname,
          status: response.status(),
        });
    });
    await page.goto("http://127.0.0.1:14200/#settings");
    await page.getByRole("switch", { name: "큰 글자", exact: true }).click();
    await page
      .getByRole("textbox", { name: "공개 API 서버 주소", exact: true })
      .fill(origin.origin);
    await page.getByRole("button", { name: "서버 연결하기" }).click();
    await page.goto("http://127.0.0.1:14200/#people");
    await page
      .getByRole("heading", { name: "아직 공개된 인물이 없어요", exact: true })
      .waitFor({ timeout: 20000 });
    assert.equal(await page.locator(".person-card").count(), 0);
    await page
      .getByRole("button", { name: "공개 목록 새로고침", exact: true })
      .click();
    await page
      .getByRole("heading", { name: "아직 공개된 인물이 없어요", exact: true })
      .waitFor({ timeout: 20000 });
    const geometry = await page.evaluate(() => ({
      width: innerWidth,
      scrollWidth: document.documentElement.scrollWidth,
    }));
    assert.equal(geometry.width, width);
    assert.ok(geometry.scrollWidth <= width);
    await page.screenshot({
      path: fileURLToPath(new URL(`empty-${width}.png`, output)),
    });
    await page.goto("http://127.0.0.1:14200/#person/__public_probe_missing__");
    await page
      .getByRole("heading", { name: "공개된 인물 문서가 없어요", exact: true })
      .waitFor({ timeout: 20000 });
    await page.screenshot({
      path: fileURLToPath(new URL(`person-404-${width}.png`, output)),
    });
    await page.getByRole("button", { name: "뒤로", exact: true }).click();
    await page
      .getByRole("heading", { name: "아직 공개된 인물이 없어요", exact: true })
      .waitFor({ timeout: 20000 });
    report.checks.push({
      width,
      empty: true,
      missingPerson: 404,
      returnedToDirectory: true,
      ...geometry,
    });
    await context.close();
  }
  assert.equal(report.pageErrors.length, 0);
  assert.ok(
    report.responses.some(
      (item) => item.path === "/api/v1/knowledge/people" && item.status === 200,
    ),
  );
  report.status = "passed";
} catch (error) {
  report.status = "failed";
  report.error = error.stack;
  process.exitCode = 1;
} finally {
  await writeFile(
    new URL("browser-report.json", output),
    JSON.stringify(report, null, 2),
  );
  await browser.close();
}
