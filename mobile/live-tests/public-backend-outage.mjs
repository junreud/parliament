import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import { writeFile } from "node:fs/promises";
import { chromium } from "playwright";

// Opt-in fault injection: supply only the PID of the development backend you
// started for this test. Never discover or interrupt an unrelated process.
const pid = Number(process.env.PARLIAMENT_OWNED_BACKEND_PID);
assert.ok(Number.isSafeInteger(pid) && pid > 1);
assert.equal(
  process.env.PARLIAMENT_ALLOW_LOCAL_OUTAGE,
  "owned-development-server",
);
const origin = new URL(process.env.PARLIAMENT_PUBLIC_API_ORIGIN || "");
assert.equal(origin.protocol, "https:");
const output = new URL("../artifacts/public-live/", import.meta.url);
const report = {
  origin: origin.origin,
  injected: "brief SIGSTOP of owned development backend; always SIGCONT",
  intercepted: false,
};
const browser = await chromium.launch({ headless: true });
let paused = false;
try {
  const page = await browser.newPage({
    viewport: { width: 412, height: 915 },
    isMobile: true,
    hasTouch: true,
  });
  await page.goto("http://127.0.0.1:14200/#settings");
  await page
    .getByRole("textbox", { name: "공개 API 서버 주소" })
    .fill(origin.origin);
  process.kill(pid, "SIGSTOP");
  paused = true;
  try {
    const upstream = fetch(new URL("/api/v1/knowledge/people", origin), {
      signal: AbortSignal.timeout(18000),
    });
    await page.getByRole("button", { name: "서버 연결하기" }).click();
    await page.goto("http://127.0.0.1:14200/#people");
    await page
      .getByRole("heading", {
        name: "인물 목록을 불러오지 못했어요",
        exact: true,
      })
      .waitFor({ timeout: 20000 });
    assert.equal(await page.locator(".person-card").count(), 0);
    await page.screenshot({
      path: fileURLToPath(new URL("real-outage-error.png", output)),
    });
    const response = await upstream;
    assert.equal(response.status, 503);
    assert.deepEqual(await response.json(), {
      error: "public_api_unavailable",
    });
    report.httpStatus = 503;
    report.errorUi = true;
    report.previewFallback = false;
  } finally {
    process.kill(pid, "SIGCONT");
    paused = false;
  }
  await page
    .getByRole("button", { name: "인물 목록 재시도", exact: true })
    .click();
  await page
    .getByRole("heading", { name: "아직 공개된 인물이 없어요", exact: true })
    .waitFor({ timeout: 20000 });
  report.retryRecovered = true;
  report.status = "passed";
} catch (error) {
  report.status = "failed";
  report.error = error.stack;
  process.exitCode = 1;
} finally {
  if (paused) process.kill(pid, "SIGCONT");
  await writeFile(
    new URL("outage-report.json", output),
    JSON.stringify(report, null, 2),
  );
  await browser.close();
}
