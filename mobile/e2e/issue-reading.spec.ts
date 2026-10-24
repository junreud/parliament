import { test, expect, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";

// Same backend-generated reading. Other endpoints are isolated UI-contract fixtures.
const reading = JSON.parse(
  readFileSync(
    new URL(
      "../../web/tests/fixtures/issue-reading-v1-success.json",
      import.meta.url,
    ),
    "utf8",
  ),
);
async function setup(page: Page, response?: () => unknown | number) {
  await page.addInitScript(() =>
    localStorage.setItem(
      "parliament.mobile.v1",
      JSON.stringify({
        mode: "live",
        origin: "https://records.example.org",
        fontSize: "large",
        reducedMotion: true,
      }),
    ),
  );
  await page.route("https://records.example.org/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/v1/issues/test-issue/reading") {
      const value = response?.() ?? reading;
      return typeof value === "number"
        ? route.fulfill({ status: value, body: "{}" })
        : route.fulfill({ json: value });
    }
    if (path === "/api/v1/people/test-person/profile")
      return route.fulfill({
        json: {
          id: "test-person",
          name: "합성 인물",
          kind: "person",
          tenures: [],
          activities: [],
          relatedIssues: [],
          facts: [
            {
              label: "검사용 소개",
              value: "실제 정치 인물이 아닌 UI 검사 자료",
              evidenceIds: ["test-evidence"],
            },
          ],
        },
      });
    if (path === "/api/v1/evidence/test-evidence")
      return route.fulfill({ json: reading.evidence[0] });
    return route.fulfill({ status: 404, body: "{}" });
  });
}

for (const width of [360, 412])
  test(`${width}px 큰 글자에서 해설·관련 인물·근거와 펼침·초점·문단으로 복귀한다`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 800 });
    await setup(page);
    await page.goto("/#issue/test-issue");
    await expect(
      page.getByRole("heading", { name: reading.title, exact: true }),
    ).toBeVisible();
    await expect(
      page.getByText(reading.currentStage, { exact: true }),
    ).toBeVisible();
    await page.getByText("경과와 쟁점 더 읽기", { exact: true }).click();
    const fact = page.locator('[data-reader-anchor="block-f1"]');
    const evidence = fact.getByRole("button", {
      name: "문단 근거 1",
      exact: true,
    });
    await evidence.scrollIntoViewIfNeeded();
    await evidence.focus();
    const y = await page.evaluate(() => window.scrollY);
    expect(y).toBeGreaterThan(0);
    await evidence.click();
    await expect(
      page.getByRole("heading", { name: "합성 원문" }),
    ).toBeVisible();
    await page.getByRole("button", { name: "뒤로", exact: true }).click();
    await expect(evidence).toBeFocused();
    await expect(page.locator(".issue-more")).toHaveAttribute("open", "");
    expect(
      Math.abs((await page.evaluate(() => window.scrollY)) - y),
    ).toBeLessThan(8);

    const person = page.getByRole("button", {
      name: "관련 인물 합성 인물 미리보기",
    });
    await person.scrollIntoViewIfNeeded();
    await person.click();
    await page.getByRole("button", { name: "인물 전체 보기" }).click();
    await expect(
      page.getByRole("heading", { name: "합성 인물", exact: true }),
    ).toBeVisible();
    await page.getByRole("button", { name: "근거 1", exact: true }).click();
    await expect(
      page.getByRole("heading", { name: "합성 원문" }),
    ).toBeVisible();
    await page.goBack();
    await expect(
      page.getByRole("heading", { name: "합성 인물", exact: true }),
    ).toBeVisible();
    await page.goBack();
    await expect(person).toBeFocused();
    await expect(page.locator(".issue-more")).toHaveAttribute("open", "");
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await page.screenshot({
      path: `artifacts/first-issue/reading-return-${width}.png`,
      fullPage: true,
    });
  });

for (const [value, heading] of [
  [400, "해설 주소를 확인해 주세요"],
  [404, "공개된 해설을 찾지 못했어요"],
  [409, "해설의 공개 버전을 다시 확인해 주세요"],
  [503, "해설을 불러오지 못했어요"],
  [{ ...reading, publicationState: "pending" }, "해설을 불러오지 못했어요"],
] as const)
  test(`해설 ${typeof value === "number" ? value : "미검토 응답"}를 공개 성공으로 바꾸지 않는다`, async ({
    page,
  }) => {
    await setup(page, () => value);
    await page.goto("/#issue/test-issue");
    await expect(page.getByRole("heading", { name: heading })).toBeVisible();
    await expect(
      page.getByRole("heading", { name: reading.title, exact: true }),
    ).toHaveCount(0);
  });

test("해설 재조회가 새 버전과 철회를 반영하고 이전 글을 남기지 않는다", async ({
  page,
}) => {
  let revision = 1;
  await setup(page, () =>
    revision === 3
      ? 404
      : revision === 2
        ? {
            ...reading,
            version: `reading_${"2".repeat(64)}`,
            summary: "다시 검토한 합성 요약",
          }
        : reading,
  );
  await page.goto("/#issue/test-issue");
  await expect(
    page.getByRole("heading", { name: reading.title, exact: true }),
  ).toBeVisible();
  revision = 2;
  await page.getByRole("button", { name: "공개 해설 새로고침" }).click();
  await expect(
    page.getByText("다시 검토한 합성 요약", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("새 공개 버전을 확인했어요.", { exact: true }),
  ).toBeVisible();
  revision = 3;
  await page.getByRole("button", { name: "공개 해설 새로고침" }).click();
  await expect(
    page.getByRole("heading", { name: "공개된 해설을 찾지 못했어요" }),
  ).toBeVisible();
  await expect(
    page.getByText("다시 검토한 합성 요약", { exact: true }),
  ).toHaveCount(0);
});
