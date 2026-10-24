import { expect, test } from "@playwright/test";
import { PREVIEW_RECORDS } from "../src/preview";

test("모바일 첫 화면에서 첫 기록의 읽기 행동이 하단 메뉴 위에 보인다", async ({
  page,
}) => {
  await page.setViewportSize({ width: 412, height: 915 });
  await page.goto("/");

  const card = page.locator(".record-card").first();
  const read = card.getByRole("button", { name: /기록 읽기/ });
  const news = page.locator(".home-news");
  await expect(read).toBeInViewport();
  const readBounds = await read.boundingBox();
  const navBounds = await page.locator(".bottom-nav").boundingBox();
  const cardBounds = await card.boundingBox();
  const newsBounds = await news.boundingBox();
  expect(readBounds).not.toBeNull();
  expect(navBounds).not.toBeNull();
  expect(cardBounds).not.toBeNull();
  expect(newsBounds).not.toBeNull();
  expect(readBounds!.y + readBounds!.height).toBeLessThan(navBounds!.y);
  expect(cardBounds!.y).toBeLessThan(newsBounds!.y);
  for (const control of [
    page.getByRole("button", { name: "검색", exact: true }),
    page.getByRole("button", { name: "전체 기록" }),
    page.getByRole("button", { name: "주제·유형 필터" }),
    card.getByRole("button", { name: "저장", exact: true }),
    read,
  ]) {
    const bounds = await control.boundingBox();
    expect(bounds).not.toBeNull();
    expect(bounds!.height).toBeGreaterThanOrEqual(44);
  }
  expect(
    await page
      .locator(".bottom-nav")
      .evaluate((element) => getComputedStyle(element).backgroundColor),
  ).toBe("rgb(255, 255, 255)");
  await page.evaluate(() => document.fonts.ready);
  await page.screenshot({
    path: "artifacts/home-v2-412.png",
    animations: "disabled",
  });
});

test("홈에서 공개 기록을 바로 검색하고 탐색 결과로 이어진다", async ({
  page,
}) => {
  await page.setViewportSize({ width: 360, height: 800 });
  await page.goto("/");

  await expect(
    page.getByRole("heading", {
      name: /지금 어느 단계인지.*기록으로 확인하세요/,
    }),
  ).toBeVisible();
  await page.getByRole("searchbox", { name: "공개 기록 검색" }).fill("주거");
  await page.getByRole("button", { name: "검색", exact: true }).click();

  await expect(page).toHaveURL(/#explore$/);
  await expect(
    page.getByRole("heading", { name: "‘주거’ 공개 기록 검색 결과" }),
  ).toBeVisible();
  await expect(
    page.getByRole("searchbox", { name: "공개 기록 검색" }),
  ).toHaveValue("주거");
  await expect(
    page.getByRole("heading", {
      name: "주거를 바꾸는 법안, 지금은 어떤 단계일까요?",
    }),
  ).toBeVisible();
  await page.getByRole("button", { name: "검색 지우기" }).click();
  await expect(
    page.getByRole("heading", { name: "주제별 공개 기록" }),
  ).toBeVisible();
  await expect(
    page.getByRole("searchbox", { name: "공개 기록 검색" }),
  ).toHaveValue("");
});

test("기록 카드에는 읽기와 저장 행동이 각각 하나씩 보인다", async ({
  page,
}) => {
  await page.goto("/");
  const card = page.locator(".record-card").first();

  await expect(card.getByRole("button", { name: /기록 읽기/ })).toHaveCount(1);
  await expect(
    card.getByRole("button", { name: "저장", exact: true }),
  ).toBeVisible();

  await card.getByRole("button", { name: "저장", exact: true }).click();
  await expect(card.getByRole("button", { name: "저장 해제" })).toBeVisible();
  await card.getByRole("button", { name: /기록 읽기/ }).click();
  await expect(
    page.getByRole("button", { name: "저장 해제", exact: true }),
  ).toHaveCount(1);
  await expect(
    page.getByRole("button", { name: "저장 해제", exact: true }),
  ).toContainText("저장 해제");
});

test("공개 기록과 검토 전 뉴스 후보와 법령을 별도 영역으로 구분한다", async ({
  page,
}) => {
  await page.goto("/");

  await expect(page.locator(".records-list .radar-entry")).toHaveCount(0);
  await expect(page.locator(".records-list .law-shelf")).toHaveCount(0);
  await expect(page.locator(".record-card.featured")).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: /뉴스에서 포착한 이슈 후보/ }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "법령 기본정보" }),
  ).toBeVisible();
  await expect(page.locator(".mode-banner")).toContainText("활동은 화면 예시");
});

test("기록 상세의 첫 화면에서 단계와 실제 발생일을 확인한다", async ({
  page,
}) => {
  await page.setViewportSize({ width: 412, height: 915 });
  const record = {
    ...PREVIEW_RECORDS[0],
    id: "focus-detail",
    title: "발표된 정책의 단계 확인",
    occurredAt: "2026-10-07T00:00:00Z",
    sourceUrl: "https://www.assembly.go.kr/",
  };
  await page.addInitScript(() =>
    localStorage.setItem(
      "parliament.mobile.v1",
      JSON.stringify({ mode: "live", origin: "https://records.example.org" }),
    ),
  );
  await page.route("https://records.example.org/**", (route) =>
    route.fulfill({ json: record }),
  );
  await page.goto("/#activity/focus-detail");

  const heading = page.locator(".detail-heading");
  await expect(
    heading.getByRole("heading", { name: record.title }),
  ).toBeVisible();
  await expect(heading).toContainText(/공식 발표.*발표.*발생 2026.*10.*07/s);
  await expect(
    page
      .getByRole("navigation", { name: "기록 목차" })
      .getByRole("button", { name: "요약" }),
  ).toBeVisible();
  await page.evaluate(() => document.fonts.ready);
  await page.screenshot({
    path: "artifacts/detail-refresh.png",
    animations: "disabled",
  });
});

test("같은 공식 원문의 열기 버튼을 읽기 화면에서 반복하지 않는다", async ({
  page,
}) => {
  const sourceUrl = "https://www.assembly.go.kr/";
  const record = {
    ...PREVIEW_RECORDS[0],
    id: "focus-source",
    sourceUrl,
    evidence: [
      {
        id: "evidence-1",
        sourceUrl,
        excerpt: "합성 검증용 원문 발췌",
        locator: "검증 문서 3쪽",
        sourceVersion: "fixture-v1",
      },
    ],
  };
  await page.addInitScript(() =>
    localStorage.setItem(
      "parliament.mobile.v1",
      JSON.stringify({ mode: "live", origin: "https://records.example.org" }),
    ),
  );
  await page.route("https://records.example.org/**", (route) =>
    route.fulfill({ json: record }),
  );
  await page.goto("/#activity/focus-source");
  await expect(page.getByRole("heading", { name: record.title })).toBeVisible();

  await expect(
    page.getByRole("button", { name: "공식 원문 열기" }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "출처에서 직접 확인하기" }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "근거 1 자세히 보기" }).click();
  await expect(
    page
      .getByRole("dialog", { name: "근거 1" })
      .getByRole("button", { name: "공식 원문 열기" }),
  ).toBeVisible();
});
