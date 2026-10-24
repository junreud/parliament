import { test, expect } from "@playwright/test";
import { PREVIEW_RECORDS } from "../src/preview";

const record = {
  ...PREVIEW_RECORDS[0],
  id: "note-fixture",
  title: "해설 읽기 계약을 확인하는 합성 기록",
  summary: "실제 정치 사건이 아닌 자동 검증용 자료입니다.",
  sourceUrl: "https://www.assembly.go.kr/fixture-only",
  evidence: [
    {
      id: "source-fixture",
      sourceUrl: "https://www.assembly.go.kr/fixture-only",
      excerpt: "검증용 원문 발췌입니다.",
      locator: "검증 문서 3쪽",
      sourceVersion: "fixture-v2",
    },
    {
      id: "unsafe-fixture",
      sourceUrl: "https://untrusted.example/",
      excerpt: "허용되지 않은 원문 주소의 검증용 발췌입니다.",
      locator: "검증 문서 4쪽",
      sourceVersion: "fixture-v2",
    },
  ],
};

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() =>
    localStorage.setItem(
      "parliament.mobile.v1",
      JSON.stringify({ mode: "live", origin: "https://records.example.org" }),
    ),
  );
  await page.route("https://records.example.org/**", (route) => {
    if (
      new URL(route.request().url()).pathname ===
      "/api/v1/activities/note-fixture"
    )
      return route.fulfill({ json: record });
    return route.fulfill({ status: 404, body: "{}" });
  });
});

test("목차가 라우트를 유지하며 본문의 해당 제목으로 이동한다", async ({
  page,
}) => {
  await page.goto("/#activity/note-fixture");
  await expect(page.getByRole("heading", { name: record.title })).toBeVisible();
  await page
    .getByRole("navigation", { name: "기록 목차" })
    .getByRole("button", { name: "근거", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "공식 근거", exact: true }),
  ).toBeFocused();
  await expect(page).toHaveURL(/#activity\/note-fixture$/);
});

test("근거 시트에서 문서 위치와 버전을 확인하고 Escape로 읽던 버튼에 복귀한다", async ({
  page,
}) => {
  await page.goto("/#activity/note-fixture");
  const trigger = page.getByRole("button", {
    name: "근거 1 자세히 보기",
    exact: true,
  });
  await trigger.click();
  const dialog = page.getByRole("dialog", { name: "근거 1" });
  await expect(dialog).toBeVisible();
  await expect(
    dialog.getByText("검증 문서 3쪽", { exact: true }),
  ).toBeVisible();
  await expect(dialog.getByText("fixture-v2", { exact: true })).toBeVisible();
  await expect(
    dialog.getByText("검증용 원문 발췌입니다.", { exact: true }),
  ).toBeVisible();
  await dialog.screenshot({
    path: "artifacts/note-source-sheet.png",
    animations: "disabled",
  });
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(trigger).toBeFocused();
});

test("허용되지 않은 원문은 시트에서도 외부 열기 동작을 제공하지 않는다", async ({
  page,
}) => {
  await page.goto("/#activity/note-fixture");
  await page
    .getByRole("button", { name: "근거 2 자세히 보기", exact: true })
    .click();
  const dialog = page.getByRole("dialog", { name: "근거 2" });
  await expect(dialog).toBeVisible();
  await expect(
    dialog.getByRole("button", { name: "공식 원문 열기" }),
  ).toHaveCount(0);
  await expect(
    dialog.getByText("안전하게 열 수 있는 공식 원문 주소를 확인하지 못했어요."),
  ).toBeVisible();
});
