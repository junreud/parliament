import assert from "node:assert/strict";
import { createServer } from "node:http";
import { spawn } from "node:child_process";
import { readFile, writeFile, mkdir } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { chromium } from "../../mobile/node_modules/playwright-core/index.mjs";

const root = fileURLToPath(new URL("../", import.meta.url));
const output = path.join(root, "artifacts", "issue-reading");
await mkdir(output, { recursive: true });
const original = JSON.parse(await readFile(new URL("../tests/fixtures/issue-reading-v1-success.json", import.meta.url), "utf8"));
// Only the issue routing identifier changes for this isolated UI fixture.
// Roles, contexts and evidence are the exact backend synthetic response.
const reading = { ...original, issueId: "child-support-advance" };
const calls = [];
let responseState = "ok";
let version = 1;
const mock = createServer((req, res) => {
  const requestPath = new URL(req.url, "http://localhost").pathname;
  calls.push(requestPath);
  res.setHeader("Content-Type", "application/json");
  res.setHeader("Cache-Control", "no-store");
  const reply = (status, value) => { res.writeHead(status); res.end(JSON.stringify(value)); };
  if (requestPath === "/api/v1/issues/child-support-advance/reading") {
    if (responseState !== "ok") return reply(Number(responseState), { error: "isolated-test" });
    return reply(200, version === 1 ? reading : { ...reading, version: `reading_${"2".repeat(64)}`, summary: "다시 검토한 합성 요약" });
  }
  if (requestPath === "/api/v1/people/test-person/profile") return reply(200, {
    id: "test-person", name: "합성 인물", kind: "person", tenures: [], activities: [], relatedIssues: [],
    facts: [{ label: "검사용 소개", value: "UI 검사만을 위한 합성 인물", evidenceIds: ["test-evidence"] }],
  });
  if (requestPath === "/api/v1/evidence/test-evidence") return reply(200, original.evidence[0]);
  return reply(404, { error: "not-found" });
});
await new Promise(resolve => mock.listen(0, "127.0.0.1", resolve));
const reserve = createServer();
await new Promise(resolve => reserve.listen(0, "127.0.0.1", resolve));
const port = reserve.address().port;
await new Promise(resolve => reserve.close(resolve));
const origin = `http://127.0.0.1:${port}`;
let nextLog = "";
const next = spawn(process.execPath, ["node_modules/next/dist/bin/next", "dev", "--hostname", "127.0.0.1", "--port", String(port)], {
  cwd: root, env: { ...process.env, BACKEND_URL: `http://127.0.0.1:${mock.address().port}`, PUBLIC_BASE_URL: origin, EDITORIAL_PREVIEW_ENABLED: "false" }, stdio: ["ignore", "pipe", "pipe"],
});
next.stdout.on("data", chunk => { nextLog += chunk.toString(); });
next.stderr.on("data", chunk => { nextLog += chunk.toString(); });
let browser;
let activePage;
let stage = "startup";
const report = { synthetic: true, publicDataVerified: false, results: [] };
try {
  let ready = false;
  for (let i = 0; i < 120; i++) {
    if (next.exitCode !== null) throw new Error(`isolated Next process exited: ${next.exitCode}`);
    try { await fetch(origin + "/start"); ready = true; break; } catch { await new Promise(resolve => setTimeout(resolve, 500)); }
  }
  assert(ready, "isolated web server did not start");
  browser = await chromium.launch({ headless: true });
  for (const width of [360, 412]) {
    const context = await browser.newContext({ viewport: { width, height: 800 }, reducedMotion: "reduce" });
    const page = await context.newPage();
    activePage = page;
    const errors = [];
    page.on("pageerror", error => errors.push(error.message));
    await page.goto(origin + "/issues/child-support-advance");
    await page.getByRole("heading", { name: "시험 해설", exact: true }).waitFor();
    await page.addStyleTag({ content: ".editorial-article p,.editorial-article a {font-size:20px!important;line-height:1.8!important}" });
    await page.getByText("경과와 쟁점 더 읽기", { exact: true }).click();
    const target = page.locator('[data-reader-focus="block-f1-test-evidence"]');
    await target.scrollIntoViewIfNeeded();
    await target.focus();
    const y = await page.evaluate(() => scrollY);
    await target.click();
    await page.getByRole("heading", { name: "합성 원문", exact: true }).waitFor();
    const count = calls.filter(p => p.endsWith("/reading")).length;
    await page.goBack();
    await target.waitFor();
    stage = "evidence-return-focus";
    await page.waitForFunction(() => document.activeElement?.getAttribute("data-reader-focus") === "block-f1-test-evidence");
    assert(await page.locator("details").first().getAttribute("open") !== null, "reading disclosure closed on return");
    const difference = Math.abs((await page.evaluate(() => scrollY)) - y);
    assert(difference < 12, `reading position changed by ${difference}px`);
    assert(calls.filter(p => p.endsWith("/reading")).length > count, "return did not recheck the public reading");
    const person = page.getByRole("link", { name: "관련 인물 · 합성 인물 →" });
    await person.click();
    await page.getByRole("heading", { name: "합성 인물", exact: true }).waitFor();
    await page.goBack();
    await person.waitFor();
    stage = "person-return-focus";
    await page.waitForFunction(() => document.activeElement?.getAttribute("data-reader-focus") === "person-b1-test-person");
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), "horizontal overflow");
    await page.screenshot({ path: path.join(output, `web-return-${width}.png`) });
    assert.deepEqual(errors, []);
    report.results.push({ width, enlargedTextCss: true, returnDelta: difference, publicRechecked: true, pageErrors: errors });
    await context.close();
  }
  const page = await browser.newPage();
  await page.goto(origin + "/issues/child-support-advance");
  version = 2;
  await page.getByRole("button", { name: "공개 해설 새로고침" }).click();
  await page.getByText("다시 검토한 합성 요약", { exact: true }).waitFor();
  await page.getByText("새 공개 버전을 확인했어요.", { exact: true }).waitFor();
  responseState = "404";
  const withdrawn = await page.reload();
  assert.equal(withdrawn.status(), 404);
  assert.equal(await page.getByText("다시 검토한 합성 요약", { exact: true }).count(), 0);
  for (const [status, heading] of [["409", "해설의 공개 버전을 다시 확인해 주세요"], ["503", "해설을 불러오지 못했어요"]]) {
    responseState = status;
    await page.reload();
    await page.getByRole("heading", { name: heading }).waitFor();
  }
  responseState = "ok";
  await page.getByRole("button", { name: "공개 해설 새로고침" }).click();
  await page.getByRole("heading", { name: "시험 해설", exact: true }).waitFor();
  assert(!calls.some(p => /admin|graphrag|sqlite/i.test(p)));
  report.results.push({ versionRefresh: true, withdrawalHttp404: true, conflict: true, unavailable: true, retry: true });
  report.status = "passed";
} catch (error) {
  report.status = "failed";
  report.error = error.message;
  report.stage = stage;
  if (activePage && !activePage.isClosed()) {
    report.debug = await activePage.evaluate(() => ({
      url: location.href, y: scrollY, active: document.activeElement?.outerHTML.slice(0, 500),
      state: history.state, expanded: Array.from(document.querySelectorAll("details")).map(d => d.open),
      saved: Object.fromEntries(Object.entries(sessionStorage).filter(([k]) => k.startsWith("parliament:issue-reading:"))),
    })).catch(() => null);
    await activePage.screenshot({ path: path.join(output, "web-failure.png") }).catch(() => {});
  }
  process.exitCode = 1;
} finally {
  await browser?.close();
  next.kill("SIGTERM");
  await new Promise(resolve => { if (next.exitCode !== null) resolve(); else next.once("exit", resolve); });
  mock.closeAllConnections();
  await new Promise(resolve => mock.close(resolve));
  await writeFile(path.join(output, "web-browser-report.json"), JSON.stringify(report, null, 2));
  await writeFile(path.join(output, "isolated-next.log"), nextLog);
  process.stdout.write(JSON.stringify(report) + "\n");
}
