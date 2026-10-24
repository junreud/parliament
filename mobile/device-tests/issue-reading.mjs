import assert from "node:assert/strict";
import { mkdir, writeFile } from "node:fs/promises";
import { _android } from "playwright";

// Opt-in checks against the installed app. No HTTP interception or plugin mocks.
const output = new URL("../artifacts/issue-device/", import.meta.url);
await mkdir(output, { recursive: true });
const devices = await _android.devices({ omitDriverInstall: true });
const device = devices.find((item) => item.serial() === "emulator-5554");
assert.ok(device, "The approved parliament-flow emulator must be running.");
const report = {
  model: device.model(),
  serial: device.serial(),
  checks: [],
  limitations: [
    "Android emulator only; physical Galaxy/One UI is unverified.",
    "No approved public reading or API origin supplied. Native publication success and HTTP status-specific flows remain unverified.",
  ],
};
const shell = async (command) =>
  (await device.shell(command)).toString().trim();
const capture = async (name) => {
  // DOM visibility can precede Android SurfaceFlinger presenting the WebView.
  // Wait for the rendered frame, then require stable native pixels at the target size.
  await page.evaluate(async () => {
    await document.fonts.ready;
    await new Promise(requestAnimationFrame);
    await new Promise(requestAnimationFrame);
  });
  await page.screenshot();
  const expectedWidth = await page.evaluate(() =>
    Math.round(innerWidth * devicePixelRatio),
  );
  let previous;
  for (let attempt = 0; attempt < 10; attempt++) {
    await new Promise((resolve) => setTimeout(resolve, 250));
    const pixels = await device.shell("screencap -p");
    if (pixels.readUInt32BE(16) === expectedWidth && previous?.equals(pixels)) {
      await writeFile(new URL(name, output), pixels);
      return;
    }
    previous = pixels;
  }
  throw new Error("Native capture did not settle at the requested viewport.");
};
let page;
let saved;
let originalSize;
let originalDensity;
try {
  originalSize = await shell("wm size");
  originalDensity = await shell("wm density");
  await shell("am start -n dev.parliament.flow/.MainActivity");
  page = await (await device.webView({ pkg: "dev.parliament.flow" })).page();
  await page.waitForSelector(".app-shell");
  assert.equal(
    await page.evaluate(() => window.Capacitor?.isNativePlatform()),
    true,
  );
  saved = await page.evaluate(() => ({
    settings: localStorage.getItem("parliament.mobile.v1"),
    session: Object.fromEntries(Object.entries(sessionStorage)),
  }));
  await page.evaluate(() => {
    sessionStorage.clear();
    localStorage.setItem(
      "parliament.mobile.v1",
      JSON.stringify({
        mode: "preview",
        origin: "",
        fontSize: "large",
        reducedMotion: true,
        haptics: false,
      }),
    );
  });
  await page.goto(new URL("#home", page.url()).href);
  await page.reload();
  for (const width of [360, 412]) {
    await shell(`wm size ${width * 3}x${915 * 3}`);
    await shell("wm density 480");
    await page.waitForFunction((expected) => innerWidth === expected, width);
    const home = page.locator(".home-radar");
    await home
      .getByRole("heading", { name: "화제 이슈", exact: true })
      .waitFor();
    const geometry = await page.evaluate(() => ({
      width: innerWidth,
      scrollWidth: document.documentElement.scrollWidth,
      font: document.querySelector(".app-shell")?.dataset.fontSize,
      searchBottom: document
        .querySelector(".record-search-control")
        ?.getBoundingClientRect().bottom,
      navTop: document.querySelector(".bottom-nav")?.getBoundingClientRect()
        .top,
    }));
    assert.equal(geometry.font, "large");
    assert.ok(geometry.scrollWidth <= width);
    assert.ok(geometry.searchBottom < geometry.navTop);
    assert.ok((await home.locator(".radar-card").count()) <= 3);
    await capture(`ranking-large-${width}.png`);
    report.checks.push({
      name: "large-font ranking home and search reachability",
      ...geometry,
    });
    await page.evaluate(() => {
      location.hash = "#issue/child-support-advance";
    });
    await page
      .getByRole("heading", {
        name: "공개 기록 모드에서 해설을 읽을 수 있어요",
        exact: true,
      })
      .waitFor();
    assert.equal(await page.locator(".issue-reading").count(), 0);
    await capture(`reading-unconfigured-${width}.png`);
    await shell("input keyevent KEYCODE_BACK");
    await home
      .getByRole("heading", { name: "화제 이슈", exact: true })
      .waitFor();
    report.checks.push({
      name: "unconfigured reading and native system back",
      width,
    });
  }
  await page.evaluate(() => {
    localStorage.setItem(
      "parliament.mobile.v1",
      JSON.stringify({
        mode: "live",
        origin: "https://public-api.invalid",
        fontSize: "large",
        reducedMotion: true,
        haptics: false,
      }),
    );
    location.hash = "#issue/child-support-advance";
  });
  await page.reload();
  const failure = page.getByRole("heading", {
    name: "해설을 불러오지 못했어요",
    exact: true,
  });
  await failure.waitFor({ timeout: 20000 });
  assert.equal(await page.locator(".issue-reading").count(), 0);
  await capture("reading-native-transport-error.png");
  await page
    .getByRole("button", { name: "해설 다시 읽기", exact: true })
    .click();
  await failure.waitFor({ timeout: 20000 });
  assert.equal(await page.locator(".issue-reading").count(), 0);
  report.checks.push({
    name: "real Capacitor HTTPS transport failure and retry",
    state: "error; no public body or sample fallback",
  });
  report.status = "passed";
} catch (error) {
  report.status = "failed";
  report.error = error.stack;
  if (page) await capture("failed.png").catch(() => {});
  process.exitCode = 1;
} finally {
  if (page && saved) {
    await page
      .evaluate((value) => {
        if (value.settings === null)
          localStorage.removeItem("parliament.mobile.v1");
        else localStorage.setItem("parliament.mobile.v1", value.settings);
        sessionStorage.clear();
        for (const [key, item] of Object.entries(value.session))
          sessionStorage.setItem(key, item);
      }, saved)
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
