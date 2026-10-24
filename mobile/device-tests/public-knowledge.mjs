import assert from "node:assert/strict";
import { mkdir, writeFile } from "node:fs/promises";
import { _android } from "playwright";

// Standalone, opt-in runtime test. Uses the installed app and its real Capacitor
// transport. It never intercepts HTTP or replaces a native plugin with a mock.
const output = new URL("../artifacts/public-device/", import.meta.url);
await mkdir(output, { recursive: true });
const devices = await _android.devices({ omitDriverInstall: true });
const device = devices.find((item) => item.serial() === "emulator-5554");
assert.ok(device, "The approved parliament-flow emulator must be running.");
const report = {
  model: device.model(),
  serial: device.serial(),
  native: false,
  checks: [],
  limitations: [
    "No physical Galaxy device.",
    "No public API service origin supplied. Native successful publication reads are not verified.",
  ],
};
let page;
let saved;
let originalSize;
let originalDensity;
const shell = async (command) =>
  (await device.shell(command)).toString().trim();
const capture = async (name) =>
  writeFile(new URL(name, output), await device.shell("screencap -p"));
try {
  originalSize = await shell("wm size");
  originalDensity = await shell("wm density");
  await shell("am start -n dev.parliament.flow/.MainActivity");
  const webview = await device.webView({ pkg: "dev.parliament.flow" });
  page = await webview.page();
  await page.waitForSelector(".app-shell");
  report.native = await page.evaluate(() =>
    window.Capacitor?.isNativePlatform(),
  );
  assert.equal(report.native, true);
  saved = await page.evaluate(() =>
    localStorage.getItem("parliament.mobile.v1"),
  );
  // Isolated emulator setup; restore the previous settings in finally.
  await page.evaluate(() =>
    localStorage.setItem(
      "parliament.mobile.v1",
      JSON.stringify({
        mode: "preview",
        origin: "",
        fontSize: "large",
        reducedMotion: true,
        haptics: false,
      }),
    ),
  );
  await page.reload();
  for (const width of [360, 412]) {
    await shell(`wm size ${width * 3}x${915 * 3}`);
    await shell("wm density 480");
    await page.goto(new URL("#person/sample-haneul", page.url()).href);
    await page.getByRole("heading", { name: "김하늘", exact: true }).waitFor();
    await page.getByRole("tab", { name: "활동", exact: true }).click();
    await page.getByRole("button", { name: "이전 기록 더 보기" }).click();
    const item = page.locator(".person-activity-open").last();
    await item.click();
    await page.getByRole("button", { name: "뒤로", exact: true }).waitFor();
    await shell("input keyevent KEYCODE_BACK");
    await page.getByRole("tab", { name: "활동", exact: true }).waitFor();
    assert.equal(
      await page
        .getByRole("tab", { name: "활동", exact: true })
        .getAttribute("aria-selected"),
      "true",
    );
    assert.equal(
      await page.locator(".person-activity-open").count(),
      4,
      "Two preview pages must remain expanded.",
    );
    await page.waitForFunction(() =>
      document.activeElement?.dataset.readerFocus?.startsWith("timeline-"),
    );
    const geometry = await page.evaluate(() => ({
      width: innerWidth,
      scrollWidth: document.documentElement.scrollWidth,
      y: scrollY,
      focus: document.activeElement?.dataset.readerFocus,
    }));
    assert.equal(geometry.width, width);
    assert.ok(geometry.scrollWidth <= width);
    assert.ok(geometry.y > 0);
    await capture(`preview-history-${width}.png`);
    report.checks.push({
      name: "large-font preview history / native back / position",
      ...geometry,
    });
  }
  await page.goto(new URL("#settings", page.url()).href);
  await page
    .getByRole("textbox", { name: "공개 API 서버 주소" })
    .fill("https://public-api.invalid");
  await page.getByRole("button", { name: "서버 연결하기" }).click();
  await page.goto(new URL("#people", page.url()).href);
  await page
    .getByRole("heading", {
      name: "인물 목록을 불러오지 못했어요",
      exact: true,
    })
    .waitFor({ timeout: 20000 });
  assert.equal(await page.locator(".person-card").count(), 0);
  await capture("native-public-error.png");
  report.checks.push({
    name: "real Capacitor HTTPS transport failure",
    state: "error; no preview fallback; no person cards",
  });
  await page
    .getByRole("button", { name: "인물 목록 재시도", exact: true })
    .click();
  await page
    .getByRole("heading", {
      name: "인물 목록을 불러오지 못했어요",
      exact: true,
    })
    .waitFor({ timeout: 20000 });
  report.checks.push({ name: "native retry", state: "error remains distinct" });
  report.status = "passed";
} catch (error) {
  report.status = "failed";
  report.error = error.stack;
  if (page) await capture("failed.png").catch(() => {});
  process.exitCode = 1;
} finally {
  if (page && saved !== undefined) {
    await page
      .evaluate(
        (value) =>
          value === null
            ? localStorage.removeItem("parliament.mobile.v1")
            : localStorage.setItem("parliament.mobile.v1", value),
        saved,
      )
      .catch(() => {});
    await page.goto(new URL("#home", page.url()).href).catch(() => {});
    await page.reload().catch(() => {});
  }
  if (originalSize)
    await shell(
      originalSize.includes("Override size:")
        ? `wm size ${originalSize.split("Override size:")[1].trim()}`
        : "wm size reset",
    );
  if (originalDensity)
    await shell(
      originalDensity.includes("Override density:")
        ? `wm density ${originalDensity.split("Override density:")[1].trim()}`
        : "wm density reset",
    );
  await writeFile(
    new URL("report.json", output),
    JSON.stringify(report, null, 2),
  );
  await device.close();
}
