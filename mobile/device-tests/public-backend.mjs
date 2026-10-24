import assert from "node:assert/strict";
import { mkdir, writeFile } from "node:fs/promises";
import { _android } from "playwright";

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
const devices = await _android.devices({ omitDriverInstall: true });
const device = devices.find((item) => item.serial() === "emulator-5554");
assert.ok(device, "The approved emulator must be running.");
const report = {
  origin: origin.origin,
  model: device.model(),
  intercepted: false,
  checks: [],
};
try {
  await device.shell("am start -n dev.parliament.flow/.MainActivity");
  const page = await (
    await device.webView({ pkg: "dev.parliament.flow" })
  ).page();
  await page.waitForSelector(".app-shell");
  assert.equal(
    await page.evaluate(() => window.Capacitor?.isNativePlatform()),
    true,
  );
  await page.goto(new URL("#settings", page.url()).href);
  const large = page.getByRole("switch", { name: "큰 글자", exact: true });
  if ((await large.getAttribute("aria-checked")) !== "true")
    await large.click();
  await page
    .getByRole("textbox", { name: "공개 API 서버 주소", exact: true })
    .fill(origin.origin);
  await page.getByRole("button", { name: "서버 연결하기" }).click();
  await page.goto(new URL("#people", page.url()).href);
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
  await writeFile(
    new URL("android-empty.png", output),
    await device.shell("screencap -p"),
  );
  report.checks.push({
    native: true,
    publicEmpty: true,
    refreshed: true,
    previewFallback: false,
  });
  await page.goto(
    new URL("#evidence/__public_probe_missing__", page.url()).href,
  );
  await page
    .getByRole("heading", { name: "공개된 근거가 없어요", exact: true })
    .waitFor({ timeout: 20000 });
  await writeFile(
    new URL("android-evidence-404.png", output),
    await device.shell("screencap -p"),
  );
  await device.shell("input keyevent KEYCODE_BACK");
  // A directly opened evidence URL has no in-app reading entry to return to.
  // Existing navigation deliberately falls back to Home for this deep link.
  await page.locator(".home-screen").waitFor({ timeout: 20000 });
  assert.ok(page.url().endsWith("#home"));
  report.checks.push({ missingEvidence: 404, directLinkNativeBackHome: true });
  await page.goto(new URL("#people", page.url()).href);
  await page
    .getByRole("heading", { name: "아직 공개된 인물이 없어요", exact: true })
    .waitFor({ timeout: 20000 });
  report.status = "passed";
} catch (error) {
  report.status = "failed";
  report.error = error.stack;
  process.exitCode = 1;
} finally {
  await writeFile(
    new URL("android-report.json", output),
    JSON.stringify(report, null, 2),
  );
  await device.close();
}
