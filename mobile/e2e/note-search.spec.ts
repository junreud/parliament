import { test, expect } from "@playwright/test";

for (const width of [360, 412]) {
  test(`${width}px 검색 후 첫 결과가 주제 선택과 메뉴에 가리지 않는다`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 915 });
    await page.goto("/#explore");
    await page.getByRole("searchbox", { name: "공개 기록 검색" }).fill("주거");
    await page.getByRole("button", { name: "검색", exact: true }).click();
    const result = page.getByRole("heading", {
      name: "주거를 바꾸는 법안, 지금은 어떤 단계일까요?",
    });
    await expect(result).toBeVisible();
    const bounds = await result.boundingBox();
    const nav = await page
      .getByRole("navigation", { name: "하단 메뉴" })
      .boundingBox();
    expect(bounds!.y + bounds!.height).toBeLessThan(nav!.y);
    await expect(page.locator(".explore-topics")).toHaveCount(0);
    await page
      .getByRole("button", { name: "검색 지우기", exact: true })
      .click();
    await expect(page.locator(".explore-topics")).toBeVisible();
    await expect(page.locator(".record-card")).toHaveCount(4);
  });
}
