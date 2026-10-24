import { test, expect } from "@playwright/test";
test("미리보기·관심 주제·검색·상세·저장 지속성을 실제 조작한다", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/");
  await expect(
    page.getByText("디자인 미리보기", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "관심 주제 설정" }).click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "가족·양육" })
    .click();
  await page.getByRole("button", { name: "1개 주제와 함께 시작하기" }).click();
  await page.screenshot({
    path: "artifacts/after/interest-accessibility.png",
    fullPage: false,
  });
  await page.getByRole("button", { name: "내 관심", exact: true }).click();
  await expect(page.locator(".record-card")).toHaveCount(1);
  await page
    .getByRole("button", {
      name: "양육과 돌봄, 정책의 흐름을 살펴보세요 기록 읽기",
    })
    .click();
  await expect(
    page.getByRole("heading", {
      name: "양육과 돌봄, 정책의 흐름을 살펴보세요",
    }),
  ).toBeVisible();
  await page
    .locator(".detail-toolbar")
    .getByRole("button", { name: "저장", exact: true })
    .click();
  await page.getByRole("button", { name: "뒤로" }).click();
  await page
    .getByRole("navigation", { name: "하단 메뉴" })
    .getByRole("button", { name: "저장", exact: true })
    .click();
  await expect(page.locator(".record-card")).toHaveCount(1);
  await page.reload();
  await expect(page.locator(".record-card")).toHaveCount(1);
  await page.getByRole("button", { name: "탐색", exact: true }).click();
  await page.getByRole("searchbox", { name: "공개 기록 검색" }).fill("주거");
  await page.getByRole("button", { name: "검색", exact: true }).click();
  await expect(page.locator(".record-card")).toHaveCount(1);
  expect(errors).toEqual([]);
});
test("큰 글자와 움직임 줄이기 설정이 지속된다", async ({ page }) => {
  await page.goto("/#settings");
  await page.getByRole("switch", { name: "큰 글자" }).click();
  await page.getByRole("switch", { name: "움직임 줄이기" }).click();
  await page.reload();
  await expect(page.getByRole("switch", { name: "큰 글자" })).toBeChecked();
  await expect(page.locator(".app-shell")).toHaveAttribute(
    "data-reduced-motion",
    "true",
  );
});
for (const width of [360, 412, 768])
  test(`${width}px 화면에 가로 넘침과 하단 메뉴 가림이 없다`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 915 });
    await page.goto("/");
    await expect(
      page.getByRole("heading", {
        name: /지금 어느 단계인지.*기록으로 확인하세요/,
      }),
    ).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
    await page.screenshot({
      path: `artifacts/home-${width}.png`,
      fullPage: true,
    });
    await page.getByRole("button", { name: "설정", exact: true }).click();
    await page.getByRole("switch", { name: "큰 글자" }).click();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
    await page.screenshot({
      path: `artifacts/settings-${width}.png`,
      fullPage: true,
    });
  });
test("실제 서버 장애·빈 결과·손상된 응답을 예시와 구분한다", async ({
  page,
}) => {
  await page.addInitScript(() =>
    localStorage.setItem(
      "parliament.mobile.v1",
      JSON.stringify({ mode: "live", origin: "https://records.example.org" }),
    ),
  );
  await page.route("https://records.example.org/api/v1/activities*", (route) =>
    route.fulfill({ status: 503, body: "{}" }),
  );
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "기록을 불러오지 못했어요" }),
  ).toBeVisible();
  await expect(page.locator(".record-card")).toHaveCount(0);
  await page.route("https://records.example.org/api/v1/activities*", (route) =>
    route.fulfill({ json: { items: [], nextCursor: null } }),
  );
  await page.getByRole("button", { name: "다시 불러오기" }).click();
  await expect(
    page.getByRole("heading", { name: "아직 공개된 기록이 없어요" }),
  ).toBeVisible();
  await page.route("https://records.example.org/api/v1/activities*", (route) =>
    route.fulfill({ json: { items: [{ title: "invalid" }] } }),
  );
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "기록을 불러오지 못했어요" }),
  ).toBeVisible();
});
