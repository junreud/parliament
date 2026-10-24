import { test, expect } from "@playwright/test";

test("수집 법령 목록·상세·뒤로·새로고침을 검증한다", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/#home");
  await expect(
    page.getByRole("heading", { name: "법령 기본정보" }),
  ).toBeVisible();
  await expect(page.locator(".law-card")).toHaveCount(3);
  await expect(page.locator(".law-shelf")).toContainText("실제 수집본");
  await page
    .getByRole("button", { name: "아동수당법 기본정보 보기", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "아동수당법", exact: true }),
  ).toBeVisible();
  await expect(page.locator(".law-dates")).toContainText("2026. 06. 09.");
  await expect(page.locator(".law-dates")).toContainText("2026. 09. 10.");
  await expect(
    page.getByRole("link", { name: "국가법령정보센터 원문" }),
  ).toHaveAttribute(
    "href",
    "https://www.law.go.kr/LSW/lsInfoP.do?lsiSeq=286729",
  );
  await page.screenshot({
    path: "artifacts/law-detail-412.png",
    fullPage: true,
  });
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "아동수당법", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "뒤로", exact: true }).click();
  await expect(page.locator(".law-card")).toHaveCount(3);
  expect(errors).toEqual([]);
});
for (const width of [360, 412, 768]) {
  test(`${width}px 큰 글자에서 법령 화면이 넘치지 않는다`, async ({ page }) => {
    await page.setViewportSize({ width, height: 915 });
    await page.goto("/#settings");
    await page.getByRole("switch", { name: "큰 글자" }).click();
    await page.getByRole("button", { name: "홈", exact: true }).click();
    await expect(page.locator(".law-card")).toHaveCount(3);
    await page
      .getByRole("button", {
        name: "아동수당법 시행규칙 기본정보 보기",
        exact: true,
      })
      .click();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
    await page.screenshot({
      path: `artifacts/law-detail-large-${width}.png`,
      fullPage: true,
    });
  });
}
test("실제 API 장애를 저장 수집본으로 숨기지 않는다", async ({ page }) => {
  await page.addInitScript(() =>
    localStorage.setItem(
      "parliament.mobile.v1",
      JSON.stringify({ mode: "live", origin: "https://records.example.org" }),
    ),
  );
  await page.route("https://records.example.org/api/v1/activities*", (route) =>
    route.fulfill({ json: { items: [], nextCursor: null } }),
  );
  await page.route("https://records.example.org/api/v1/laws", (route) =>
    route.fulfill({ status: 503, body: "{}" }),
  );
  await page.goto("/#home");
  await expect(page.locator(".law-shelf")).toContainText(
    "법령을 불러오지 못했어요",
  );
  await expect(page.locator(".law-card")).toHaveCount(0);
  await page.route("https://records.example.org/api/v1/laws", (route) =>
    route.fulfill({
      json: { items: [], nextCursor: null, coverage: "공개 법령 없음" },
    }),
  );
  await page.getByRole("button", { name: "법령 다시 불러오기" }).click();
  await expect(page.locator(".law-shelf")).toContainText(
    "공개된 법령이 아직 없어요",
  );
  await expect(page.locator(".law-card")).toHaveCount(0);
});
