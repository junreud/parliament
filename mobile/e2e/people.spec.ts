import { test, expect } from "@playwright/test";
import type {
  PersonProfile,
  PublicContext,
} from "../../web/src/lib/knowledge-contracts";

test("인물 탭은 방향키와 Home·End로 탐색할 수 있다", async ({ page }) => {
  await page.goto("/#person/sample-haneul");
  const overview = page.getByRole("tab", { name: "개요", exact: true });
  await overview.focus();
  await overview.press("ArrowRight");
  await expect(
    page.getByRole("tab", { name: "활동", exact: true }),
  ).toBeFocused();
  await expect(
    page.getByRole("tab", { name: "활동", exact: true }),
  ).toHaveAttribute("aria-selected", "true");
  await page.getByRole("tab", { name: "활동", exact: true }).press("End");
  await expect(
    page.getByRole("tab", { name: "연결", exact: true }),
  ).toBeFocused();
  await page.getByRole("tab", { name: "연결", exact: true }).press("Home");
  await expect(overview).toBeFocused();
  await expect(overview).toHaveAttribute("aria-selected", "true");
});

test("공개 API 응답의 승인 이름과 시간순 커서를 실제 모드에서 연결한다", async ({
  page,
}) => {
  const sourceUrl = "https://www.assembly.go.kr/fixture-only";
  const evidence = {
    id: "ev_fixture",
    documentId: "doc_fixture",
    documentVersion: "v1",
    extractionVersion: "x1",
    segmentId: "seg_fixture",
    start: 0,
    end: 14,
    excerpt: "홍길동과 김미확인이 발언함",
    before: "",
    after: "",
    sourceUrl,
    title: "API 계약 검증용 합성 기록",
    locator: "문단 1",
    mentions: [
      {
        id: "mention_ok",
        surface: "홍길동",
        start: 0,
        end: 3,
        personId: "p_fixture",
        decision: "approved" as const,
      },
      {
        id: "mention_pending",
        surface: "김미확인",
        start: 5,
        end: 9,
        personId: "p_pending",
        decision: "pending" as const,
      },
    ],
  };
  const context: PublicContext = {
    eventId: "activity_fixture",
    eventVersion: "v1",
    changeKind: "new_record",
    activity: {
      id: "activity_fixture",
      version: "v1",
      type: "speech",
      stage: "announced",
      title: "공개 API 계약 기록",
      summary: null,
      topics: [],
      personIds: ["p_fixture"],
      billId: null,
      occurredAt: "2025-12-31T18:00:00Z",
      publishedAt: "2026-01-01T01:00:00Z",
      collectedAt: "2026-01-02T00:00:00Z",
      sourceUrl,
      evidence: [],
      votes: [],
      coverage: "fixture",
      corrected: false,
    },
    participants: [
      {
        personId: "p_fixture",
        name: "홍길동",
        role: "speaker",
        evidenceIds: ["ev_fixture"],
        organizationAtTime: null,
        positionAtTime: null,
      },
    ],
    relations: [],
    documents: [],
    evidence: [evidence],
  };
  const profile: PersonProfile = {
    id: "p_fixture",
    name: "홍길동",
    kind: "person",
    facts: [],
    tenures: [],
    activities: [],
    relatedIssues: [],
  };
  const requests: URL[] = [];
  await page.addInitScript(() =>
    localStorage.setItem(
      "parliament.mobile.v1",
      JSON.stringify({ mode: "live", origin: "https://records.example.org" }),
    ),
  );
  await page.route("https://records.example.org/**", (route) => {
    const url = new URL(route.request().url());
    requests.push(url);
    if (url.pathname.endsWith("/profile"))
      return route.fulfill({ json: profile });
    if (url.pathname.endsWith("/timeline"))
      return route.fulfill({
        json: {
          id: profile.id,
          items: url.searchParams.has("cursor") ? [] : [context],
          nextCursor: url.searchParams.has("cursor")
            ? null
            : "opaque-fixture-cursor",
        },
      });
    if (url.pathname.endsWith("/context"))
      return route.fulfill({ json: context });
    if (url.pathname.endsWith("/activity_fixture"))
      return route.fulfill({ json: context.activity });
    return route.fulfill({ json: { items: [], nextCursor: null } });
  });
  await page.goto("/#activity/activity_fixture");
  await expect(page.getByText("김미확인", { exact: false })).toBeVisible();
  await expect(
    page.getByRole("button", { name: "김미확인 인물 미리보기" }),
  ).toHaveCount(0);
  await page
    .getByRole("button", { name: "홍길동 인물 미리보기", exact: true })
    .click();
  await page.getByRole("button", { name: "인물 전체 보기" }).click();
  await expect(
    page.getByRole("heading", { name: "홍길동", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("가상 인물 · UX 예시", { exact: false }),
  ).toHaveCount(0);
  await page.getByRole("tab", { name: "활동", exact: true }).click();
  await page.getByLabel("활동 역할").selectOption("speaker");
  await expect(page.locator(".timeline-month").first()).toHaveText("202601월");
  await expect(page.locator(".person-role-chips span")).toHaveCount(1);
  await page.getByRole("button", { name: "이전 기록 더 보기" }).click();
  await expect(page.locator(".person-activity")).toHaveCount(1);
  expect(
    requests.some(
      (url) =>
        url.searchParams.get("cursor") === "opaque-fixture-cursor" &&
        url.searchParams.get("role") === "speaker",
    ),
  ).toBe(true);
  await page.getByRole("button", { name: "뒤로", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "홍길동 인물 미리보기", exact: true }),
  ).toBeVisible();
});

test("직접 열린 인물 문서의 뒤로가기가 목록과 탐색으로 이어진다", async ({
  page,
}) => {
  await page.goto("/#person/sample-haneul");
  await page.getByRole("button", { name: "뒤로", exact: true }).click();
  await expect(page).toHaveURL(/#people$/);
  await page.getByRole("button", { name: "뒤로", exact: true }).click();
  await expect(page).toHaveURL(/#explore$/);
});

test("활동에서 글을 열고 앞뒤로 이동해도 페이지·필터·읽던 위치가 보존된다", async ({
  page,
}) => {
  await page.goto("/#person/sample-haneul");
  await page.getByRole("tab", { name: "활동", exact: true }).click();
  await page.getByLabel("활동 역할").selectOption("speaker");
  await page.getByRole("button", { name: "이전 기록 더 보기" }).click();
  const last = page.locator(".person-activity-open").last();
  await last.scrollIntoViewIfNeeded();
  const before = await page.evaluate(() => window.scrollY);
  await last.click();
  await expect(page).toHaveURL(/#activity/);
  await page.getByRole("button", { name: "뒤로", exact: true }).click();
  await expect(page.getByLabel("활동 역할")).toHaveValue("speaker");
  await expect(page.locator(".person-activity")).toHaveCount(3);
  await expect
    .poll(async () =>
      Math.abs((await page.evaluate(() => window.scrollY)) - before),
    )
    .toBeLessThan(5);
  await page.goForward();
  await expect(page).toHaveURL(/#activity/);
  await page.goBack();
  await expect
    .poll(async () =>
      Math.abs((await page.evaluate(() => window.scrollY)) - before),
    )
    .toBeLessThan(5);
});

test("본문 이름에서 A→B 탐색 후 글의 같은 위치로 돌아온다", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/#activity/sample-care");
  const mention = page
    .getByRole("button", { name: "김하늘 인물 미리보기", exact: true })
    .first();
  await mention.scrollIntoViewIfNeeded();
  const before = await page.evaluate(() => window.scrollY);
  await mention.click();
  await expect(
    page.getByRole("dialog", { name: "인물 미리보기" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "인물 미리보기 닫기" }).click();
  await expect(mention).toBeFocused();
  await mention.click();
  await page.getByRole("button", { name: "인물 전체 보기" }).click();
  await expect(
    page.getByRole("heading", { name: "김하늘", exact: true }),
  ).toBeVisible();
  await page.getByRole("tab", { name: "연결", exact: true }).click();
  await page
    .getByRole("button", { name: "이서준 인물 문서", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "이서준", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "뒤로", exact: true }).click();
  await expect(
    page.getByRole("tab", { name: "연결", exact: true }),
  ).toHaveAttribute("aria-selected", "true");
  await page.getByRole("button", { name: "뒤로", exact: true }).click();
  await expect(mention).toBeVisible();
  await expect
    .poll(async () =>
      Math.abs((await page.evaluate(() => window.scrollY)) - before),
    )
    .toBeLessThan(5);
  expect(errors).toEqual([]);
});
test("시간순·기간·역할·추가 기록과 새로고침을 유지한다", async ({ page }) => {
  await page.goto("/#person/sample-haneul");
  await page.getByRole("tab", { name: "활동", exact: true }).click();
  await page.getByLabel("활동 정렬").selectOption("oldest");
  await page.getByLabel("활동 역할").selectOption("speaker");
  await expect(page.locator(".person-activity").first()).toContainText("2024");
  await page.getByRole("button", { name: "이전 기록 더 보기" }).click();
  await expect(page.locator(".person-activity")).toHaveCount(3);
  await page.reload();
  await expect(
    page.getByRole("tab", { name: "활동", exact: true }),
  ).toHaveAttribute("aria-selected", "true");
  await expect(page.getByLabel("활동 역할")).toHaveValue("speaker");
  await expect(page.getByLabel("활동 정렬")).toHaveValue("oldest");
  await expect(page.locator(".person-activity")).toHaveCount(3);
  await page.getByLabel("시작일").fill("2030-01-01");
  await page.getByRole("button", { name: "기간 적용" }).click();
  await expect(
    page.getByText("선택한 조건에서 확인된 기록이 없어요"),
  ).toBeVisible();
});
test("탐색에서 인물 검색·문서 목차·직위 이력과 자료 범위를 읽는다", async ({
  page,
}) => {
  await page.goto("/#explore");
  await page.getByRole("button", { name: "인물 위키 둘러보기" }).click();
  await page.getByRole("searchbox", { name: "인물 이름 검색" }).fill("김하늘");
  await page.getByRole("button", { name: "인물 검색하기" }).click();
  await expect(page.locator(".person-card")).toHaveCount(1);
  await page
    .getByRole("button", { name: "김하늘 인물 문서", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "직위·소속 이력" }),
  ).toBeVisible();
  await expect(
    page.getByText("가상 인물 · UX 예시", { exact: false }).first(),
  ).toBeVisible();
  await page.getByRole("button", { name: "뒤로", exact: true }).click();
  await expect(
    page.getByRole("searchbox", { name: "인물 이름 검색" }),
  ).toHaveValue("김하늘");
});
test("실제 API 오류와 미공개 인물을 예시로 바꾸지 않는다", async ({ page }) => {
  await page.addInitScript(() =>
    localStorage.setItem(
      "parliament.mobile.v1",
      JSON.stringify({ mode: "live", origin: "https://records.example.org" }),
    ),
  );
  await page.route("https://records.example.org/**", (route) =>
    route.fulfill({ status: 503, body: "{}" }),
  );
  await page.goto("/#person/p_missing");
  await expect(
    page.getByText("인물 자료를 불러오지 못했어요", { exact: true }),
  ).toBeVisible();
  await expect(page.getByText("김하늘", { exact: true })).toHaveCount(0);
});
test("360px 큰 글자와 줄인 움직임에서 문서가 넘치지 않는다", async ({
  page,
}) => {
  await page.setViewportSize({ width: 360, height: 800 });
  await page.goto("/#settings");
  await page.getByRole("switch", { name: "큰 글자" }).click();
  await page.getByRole("switch", { name: "움직임 줄이기" }).click();
  await page.goto("/#person/sample-haneul");
  await expect(
    page.getByRole("heading", { name: "김하늘", exact: true }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: "artifacts/person-wiki/large-360.png",
    fullPage: true,
  });
});
