import { test, expect } from "@playwright/test";
import { PREVIEW_RECORDS } from "../src/preview";
import { mkdir, writeFile } from "node:fs/promises";
test("잘못 인코딩한 상세 주소가 앱을 중단시키지 않는다", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/#activity/%ZZ");
  await expect(
    page.getByRole("heading", {
      name: /지금 어느 단계인지.*기록으로 확인하세요/,
    }),
  ).toBeVisible();
  expect(errors).toEqual([]);
  await page.locator(".screen").evaluate(async (el) => {
    await Promise.all(el.getAnimations().map((a) => a.finished));
  });
  await page.screenshot({
    path: "artifacts/after/malformed-route.png",
    fullPage: false,
  });
});
test("키보드로 관심 창을 닫으면 원래 버튼으로 초점이 돌아온다", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: "관심 주제 설정" }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "관심 주제 설정" }),
  ).toBeFocused();
});
test("검증된 자료·커서 이동·원문·장애 재시도를 함께 확인한다", async ({
  page,
}) => {
  await page.addInitScript(() =>
    localStorage.setItem(
      "parliament.mobile.v1",
      JSON.stringify({ mode: "live", origin: "https://records.example.org" }),
    ),
  );
  const first = {
    ...PREVIEW_RECORDS[0],
    id: "record-1",
    title: "통합 테스트용 공개 기록",
    sourceUrl: "https://www.assembly.go.kr/",
    evidence: [
      {
        id: "e1",
        sourceUrl: "https://www.assembly.go.kr/",
        excerpt: "통합 테스트용 발췌문",
        locator: "검증 자료 1쪽",
        sourceVersion: "v1",
      },
    ],
    version: "v1",
  };
  const second = {
    ...PREVIEW_RECORDS[1],
    id: "record-2",
    title: "다음 페이지 테스트 기록",
  };
  let fail = true;
  await page.route(
    "https://records.example.org/api/v1/activities*",
    (route) => {
      if (route.request().url().includes("record-1"))
        return route.fulfill({ json: first });
      if (route.request().url().includes("cursor=")) {
        if (fail) return route.fulfill({ status: 503, body: "{}" });
        return route.fulfill({
          json: { items: [first, second], nextCursor: null },
        });
      }
      return route.fulfill({ json: { items: [first], nextCursor: "page-2" } });
    },
  );
  await page.route(
    "https://records.example.org/api/v1/activities/record-1",
    (route) => route.fulfill({ json: first }),
  );
  await page.goto("/");
  await expect(page.locator(".record-card")).toHaveCount(1);
  await page.getByRole("button", { name: "다음 기록 읽기" }).click();
  await expect(page.getByRole("alert")).toBeVisible();
  await expect(page.locator(".record-card")).toHaveCount(1);
  fail = false;
  await page.getByRole("button", { name: "다음 기록 읽기" }).click();
  await expect(page.locator(".record-card")).toHaveCount(2);
  await page
    .getByRole("button", { name: "통합 테스트용 공개 기록 기록 읽기" })
    .click();
  await expect(
    page.getByText("통합 테스트용 발췌문", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "근거 1 자세히 보기" }).click();
  await expect(
    page
      .getByRole("dialog", { name: "근거 1" })
      .getByRole("button", { name: "공식 원문 열기" }),
  ).toBeVisible();
  await page.screenshot({
    path: "artifacts/detail-live-fixture.png",
    fullPage: true,
  });
});
test("움직임과 CDP 자료를 기록하고 화면 캡처의 완료 시점을 확인한다", async ({
  page,
  context,
}) => {
  await mkdir("artifacts", { recursive: true });
  const client = await context.newCDPSession(page);
  await client.send("Performance.enable");
  await client.send("Tracing.start", {
    categories: "devtools.timeline,blink.user_timing,cc,benchmark",
    transferMode: "ReturnAsStream",
  });
  await page.goto("/");
  await page.locator(".screen").evaluate(async (element) => {
    await Promise.all(
      element.getAnimations().map((animation) => animation.finished),
    );
  });
  await page.screenshot({ path: "artifacts/home-final.png", fullPage: false });
  await page.getByRole("button", { name: "관심 주제 설정" }).click();
  const duration = await page
    .getByRole("dialog")
    .evaluate((el) => getComputedStyle(el).animationDuration);
  expect(parseFloat(duration)).toBeLessThanOrEqual(0.25);
  await page.getByRole("dialog").evaluate(async (el) => {
    await Promise.all(el.getAnimations().map((a) => a.finished));
  });
  await page.screenshot({
    path: "artifacts/topics-final.png",
    fullPage: false,
  });
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "탐색", exact: true }).click();
  await page.locator(".screen").evaluate(async (el) => {
    await Promise.all(el.getAnimations().map((a) => a.finished));
  });
  await page.screenshot({
    path: "artifacts/explore-final.png",
    fullPage: false,
  });
  await page.getByRole("button", { name: "설정", exact: true }).click();
  await page.locator(".screen").evaluate(async (el) => {
    await Promise.all(el.getAnimations().map((a) => a.finished));
  });
  await page.screenshot({
    path: "artifacts/settings-final.png",
    fullPage: true,
  });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.getByRole("button", { name: "관심 주제 설정" }).click();
  expect(
    await page
      .getByRole("dialog")
      .evaluate((el) => getComputedStyle(el).animationName),
  ).toBe("none");
  await page.keyboard.press("Escape");
  const metrics = await client.send("Performance.getMetrics");
  await writeFile(
    "artifacts/performance-metrics.json",
    JSON.stringify(
      {
        environment:
          "Chromium mobile viewport 412x915; synthetic samples; not a physical Galaxy FPS result",
        metrics,
      },
      null,
      2,
    ),
  );
  const complete = new Promise<{ stream?: string }>((resolve) =>
    client.once("Tracing.tracingComplete", resolve),
  );
  await client.send("Tracing.end");
  const { stream } = await complete;
  if (!stream)
    throw new Error("CDP did not return the required performance trace stream");
  let data = "";
  let done = false;
  while (!done) {
    const part = await client.send("IO.read", { handle: stream });
    data += part.data;
    done = part.eof;
  }
  await client.send("IO.close", { handle: stream });
  await writeFile("artifacts/performance-trace.json", data);
});
