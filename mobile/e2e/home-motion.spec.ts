import { test, expect } from "@playwright/test";
import { mkdir } from "node:fs/promises";

for (const width of [360, 412]) {
  test(`${width}px 첫 화면에서 검색 입력과 행동이 메뉴 위에 보인다`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 800 });
    await page.goto("/");
    const search = page.getByRole("searchbox", { name: "공개 기록 검색" });
    const action = page.getByRole("button", { name: "검색", exact: true });
    await expect(search).toBeInViewport();
    await expect(action).toBeInViewport();
    const searchBounds = await search.boundingBox();
    const actionBounds = await action.boundingBox();
    const nav = await page.locator(".bottom-nav").boundingBox();
    expect(searchBounds).not.toBeNull();
    expect(actionBounds).not.toBeNull();
    expect(nav).not.toBeNull();
    expect(searchBounds!.y + searchBounds!.height).toBeLessThan(nav!.y);
    expect(actionBounds!.y + actionBounds!.height).toBeLessThan(nav!.y);
    await expect(page.locator(".record-card").first()).toBeAttached();
    await expect(page.locator(".hero-illustration")).toHaveCount(0);
    await expect(page.locator(".home-filters")).not.toHaveAttribute("open", "");
  });
}

test("홈의 접힌 필터를 열어 같은 주제·유형 조건을 적용한다", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: "주제·유형 필터" }).click();
  await page
    .getByRole("group", { name: "주제 필터" })
    .getByRole("button", { name: "주거", exact: true })
    .click();
  await page.getByLabel("기록 유형").selectOption("bill");
  await expect(page.locator(".record-card")).toHaveCount(1);
  await expect(
    page.getByRole("heading", {
      name: "주거를 바꾸는 법안, 지금은 어떤 단계일까요?",
    }),
  ).toBeVisible();
});

test("기록 열기와 뒤로가기가 방향을 가진 실제 View Transition으로 이어진다", async ({
  page,
}) => {
  await page.goto("/");
  await page.locator(".screen").evaluate(async (el) => {
    await Promise.all(el.getAnimations().map((a) => a.finished));
  });
  await page
    .getByRole("button", {
      name: "양육과 돌봄, 정책의 흐름을 살펴보세요 기록 읽기",
    })
    .click();
  await expect(page.locator(".screen")).toHaveAttribute(
    "data-motion-kind",
    "view-transition",
  );
  await expect(page.locator("html")).toHaveAttribute(
    "data-motion-direction",
    "forward",
  );
  await expect
    .poll(() =>
      page.evaluate(() =>
        document.getAnimations().map((a) => (a as CSSAnimation).animationName),
      ),
    )
    .toContain("flow-page-enter");
  await page.locator(".screen").evaluate(async () => {
    await Promise.all(document.getAnimations().map((a) => a.finished));
  });
  await page.getByRole("button", { name: "뒤로", exact: true }).click();
  await expect(page.locator("html")).toHaveAttribute(
    "data-motion-direction",
    "back",
  );
  await expect(page.locator(".record-card").first()).toBeVisible();
});

test("View Transition 미지원 환경에서도 이동 효과와 빠른 재탭이 안전하다", async ({
  page,
}) => {
  await page.addInitScript(() =>
    Object.defineProperty(document, "startViewTransition", {
      value: undefined,
      configurable: true,
    }),
  );
  await page.goto("/");
  await page.getByRole("button", { name: "탐색", exact: true }).click();
  await expect(page.locator(".screen")).toHaveAttribute(
    "data-motion-kind",
    "fallback",
  );
  await expect
    .poll(() => page.locator(".screen").getAttribute("data-motion-phase"))
    .toBe("entering");
  expect(
    await page
      .locator(".screen")
      .evaluate((el) =>
        el.getAnimations().some((a) => a.playState === "running"),
      ),
  ).toBe(true);
  await page.getByRole("button", { name: "설정", exact: true }).click();
  await page.getByRole("button", { name: "홈", exact: true }).click();
  await expect(page.locator(".screen")).toHaveAttribute(
    "data-motion-phase",
    "idle",
  );
  await expect(
    page.getByRole("heading", {
      name: /지금 어느 단계인지.*기록으로 확인하세요/,
    }),
  ).toBeVisible();
});

test("관심 창은 닫히는 과정도 애니메이션으로 보여주고 초점을 복원한다", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: "관심 주제 설정" }).click();
  await page.getByRole("dialog").evaluate(async (el) => {
    await Promise.all(el.getAnimations().map((a) => a.finished));
  });
  await page.getByRole("button", { name: "관심 주제 닫기" }).click();
  await expect(page.getByRole("dialog")).toHaveAttribute(
    "data-state",
    "closing",
  );
  expect(
    await page
      .getByRole("dialog")
      .evaluate((el) =>
        el.getAnimations().some((a) => a.playState === "running"),
      ),
  ).toBe(true);
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "관심 주제 설정" }),
  ).toBeFocused();
});

test("OS와 앱의 움직임 줄이기가 화면 이동과 닫기 모션을 생략한다", async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/");
  await page.getByRole("button", { name: "설정", exact: true }).click();
  await expect(page.locator(".screen")).toHaveAttribute(
    "data-motion-kind",
    "none",
  );
  await page.getByRole("switch", { name: "움직임 줄이기" }).click();
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await page.getByRole("button", { name: "홈", exact: true }).click();
  await expect(page.locator(".screen")).toHaveAttribute(
    "data-motion-kind",
    "none",
  );
  expect(
    await page.evaluate(
      () =>
        document.getAnimations().filter((a) => a.playState === "running")
          .length,
    ),
  ).toBe(0);
});

test("바뀐 홈의 최종 화면과 이동 중간 프레임을 보존한다", async ({ page }) => {
  await mkdir("artifacts/home-refresh", { recursive: true });
  await page.goto("/");
  await page.locator(".screen").evaluate(async () => {
    await Promise.all(document.getAnimations().map((a) => a.finished));
  });
  await page.screenshot({
    path: "artifacts/home-refresh/home-after.png",
    fullPage: false,
  });
  await page.getByRole("button", { name: "탐색", exact: true }).click();
  await expect
    .poll(() =>
      page.evaluate(() =>
        document.getAnimations().map((a) => (a as CSSAnimation).animationName),
      ),
    )
    .toContain("flow-page-enter");
  await page.screenshot({
    path: "artifacts/home-refresh/navigation-frame.png",
    animations: "allow",
  });
  await page.locator(".screen").evaluate(async () => {
    await Promise.all(document.getAnimations().map((a) => a.finished));
  });
  await page.screenshot({ path: "artifacts/home-refresh/explore-after.png" });
});

test("필터를 열고 다른 탭을 다녀와도 닫힌 상태와 접근성 안내가 일치한다", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: "주제·유형 필터" }).click();
  await expect(
    page.getByRole("button", { name: "주제·유형 필터" }),
  ).toHaveAttribute("aria-expanded", "true");
  await page.getByRole("button", { name: "탐색", exact: true }).click();
  await expect(page.getByRole("searchbox")).toBeVisible();
  await page.getByRole("button", { name: "홈", exact: true }).click();
  await expect(page.locator(".home-filters")).not.toHaveAttribute("open", "");
  await expect(
    page.getByRole("button", { name: "주제·유형 필터" }),
  ).toHaveAttribute("aria-expanded", "false");
});

for (const width of [360, 1280]) {
  test(`${width}×720px에서도 검색 행동이 메뉴에 가리지 않는다`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 720 });
    await page.goto("/");
    const action = page.getByRole("button", { name: "검색", exact: true });
    await expect(action).toBeInViewport();
    const bounds = await action.boundingBox();
    const nav = await page.locator(".bottom-nav").boundingBox();
    expect(bounds!.y + bounds!.height).toBeLessThan(nav!.y);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await page.evaluate(() => document.fonts.ready);
    await page.screenshot({
      path: `artifacts/home-v2-${width}.png`,
      animations: "disabled",
    });
  });
}
