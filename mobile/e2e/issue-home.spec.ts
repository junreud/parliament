import { test, expect } from "@playwright/test";
import { readFileSync } from "node:fs";
const radar = JSON.parse(
  readFileSync(new URL("./fixtures/radar.json", import.meta.url), "utf8"),
);
const reading = JSON.parse(
  readFileSync(
    new URL(
      "../../web/tests/fixtures/issue-reading-v1-success.json",
      import.meta.url,
    ),
    "utf8",
  ),
);

test("화제 후보 순서를 첫 콘텐츠로 보여주고 공개 해설만 별도로 연결한다", async ({
  page,
}) => {
  let published = false;
  await page.addInitScript(() =>
    localStorage.setItem(
      "parliament.mobile.v1",
      JSON.stringify({
        mode: "live",
        origin: "https://records.example.org",
        reducedMotion: true,
      }),
    ),
  );
  await page.route("https://records.example.org/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/v1/radar") return route.fulfill({ json: radar });
    if (path === "/api/v1/issues/child-support-advance/reading")
      return published
        ? route.fulfill({
            json: { ...reading, issueId: "child-support-advance" },
          })
        : route.fulfill({ status: 404, body: "{}" });
    return route.fulfill({ status: 404, body: "{}" });
  });
  await page.goto("/");
  const home = page.locator(".home-radar");
  await expect(
    home.getByRole("heading", { name: "화제 이슈", exact: true }),
  ).toBeVisible();
  await expect(home.locator(".radar-card")).toHaveCount(
    Math.min(3, radar.items.length),
  );
  if (radar.items.length)
    await expect(home.locator(".radar-card").first()).toContainText(
      radar.items[0].title,
    );
  const order = await page.evaluate(() => {
    const rank = document.querySelector(".home-radar")!,
      records = document.querySelector(".home-intro")!;
    return Boolean(
      rank.compareDocumentPosition(records) & Node.DOCUMENT_POSITION_FOLLOWING,
    );
  });
  expect(order).toBe(true);
  await expect(
    page.getByText("현재 공개된 선정 해설이 없어요.", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: /시험 해설.*쉬운 해설 읽기/ }),
  ).toHaveCount(0);
  published = true;
  await page.getByRole("button", { name: "선정 해설 다시 확인" }).click();
  await page.getByRole("button", { name: /시험 해설.*쉬운 해설 읽기/ }).click();
  await expect(page).toHaveURL(/#issue\/child-support-advance$/);
  await expect(
    page.getByRole("heading", { name: "시험 해설", exact: true }),
  ).toBeVisible();
});
