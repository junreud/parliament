import { test, expect, type Page } from "@playwright/test";
import {
  person,
  profile,
  evidence,
  context,
  activity,
  bill,
  alternative,
  lineage,
  graph,
} from "./fixtures/public-knowledge";

async function setup(
  page: Page,
  overrides?: (path: string, url: URL) => unknown,
) {
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
    const url = new URL(route.request().url()),
      path = url.pathname;
    const override = overrides?.(path, url);
    if (typeof override === "number")
      return route.fulfill({ status: override, body: "{}" });
    if (override !== undefined) return route.fulfill({ json: override });
    const resources: Record<string, unknown> = {
      "/api/v1/knowledge/people": { items: [person], nextCursor: null },
      [`/api/v1/people/${person.id}/profile`]: profile,
      [`/api/v1/people/${person.id}/timeline`]: {
        id: person.id,
        items: [context],
        nextCursor: null,
      },
      "/api/v1/knowledge/graph": graph,
      [`/api/v1/evidence/${evidence.id}`]: evidence,
      [`/api/v1/activities/${activity.id}`]: activity,
      [`/api/v1/activities/${activity.id}/context`]: context,
      [`/api/v1/bills/${bill.id}`]: bill,
      [`/api/v1/bills/${alternative.id}`]: alternative,
      [`/api/v1/bills/${bill.id}/lineage`]: lineage,
      [`/api/v1/bills/${alternative.id}/lineage`]: {
        ...lineage,
        id: alternative.id,
      },
    };
    return resources[path]
      ? route.fulfill({ json: resources[path] })
      : route.fulfill({ status: 404, body: "{}" });
  });
}

test("인물 목록을 갱신하면 새 공개 버전과 공개 철회를 다시 확인한다", async ({
  page,
}) => {
  let revision = 1;
  await setup(page, (path) =>
    path === "/api/v1/knowledge/people"
      ? revision === 3
        ? 404
        : {
            items: [{ ...person, name: `${person.name} v${revision}` }],
            nextCursor: null,
          }
      : undefined,
  );
  await page.goto("/#people");
  await expect(
    page.getByRole("heading", { name: `${person.name} v1` }),
  ).toBeVisible();
  revision = 2;
  await page
    .getByRole("button", { name: "공개 목록 새로고침", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: `${person.name} v2` }),
  ).toBeVisible();
  await expect(
    page.getByText(`${person.name} v1`, { exact: true }),
  ).toHaveCount(0);
  revision = 3;
  await page
    .getByRole("button", { name: "공개 목록 새로고침", exact: true })
    .click();
  await expect(
    page.getByText("인물 목록 경로를 찾지 못했어요", { exact: true }),
  ).toBeVisible();
  await expect(page.locator(".person-card")).toHaveCount(0);
});

for (const [response, title] of [
  [{ items: [], nextCursor: null }, "아직 공개된 인물이 없어요"],
  [404, "인물 목록 경로를 찾지 못했어요"],
  [503, "인물 목록을 불러오지 못했어요"],
] as const) {
  test(`인물 목록 상태 ${title}`, async ({ page }) => {
    await setup(page, (path) =>
      path === "/api/v1/knowledge/people" ? response : undefined,
    );
    await page.goto("/#people");
    await expect(
      page.getByRole("heading", { name: title, exact: true }),
    ).toBeVisible();
    await expect(page.locator(".person-card")).toHaveCount(0);
  });
}

test("다음 인물 페이지 실패는 앞 페이지를 유지하고 재시도한다", async ({
  page,
}) => {
  let fail = true;
  await setup(page, (path, url) =>
    path === "/api/v1/knowledge/people"
      ? url.searchParams.has("cursor")
        ? fail
          ? 503
          : {
              items: [{ ...person, id: "p_second", name: "두 번째 합성 인물" }],
              nextCursor: null,
            }
        : { items: [person], nextCursor: "page2" }
      : undefined,
  );
  await page.goto("/#people");
  await page.getByRole("button", { name: "다음 인물 보기" }).click();
  await expect(
    page.getByText("일부 인물 목록을 불러오지 못했어요", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: person.name, exact: true }),
  ).toBeVisible();
  fail = false;
  await page.getByRole("button", { name: "인물 목록 재시도" }).click();
  await expect(
    page.getByRole("heading", { name: "두 번째 합성 인물" }),
  ).toBeVisible();
  await expect(page.locator(".person-card")).toHaveCount(2);
});

test("프로필의 관측·효력 기간과 근거를 구분하고 새 공개 버전을 읽는다", async ({
  page,
}) => {
  let revision = 1;
  await setup(page, (path) =>
    path.endsWith("/profile")
      ? {
          ...profile,
          facts: [
            { ...profile.facts[0], value: `합성 검증 자료 v${revision}` },
          ],
        }
      : undefined,
  );
  await page.goto(`/#person/${person.id}`);
  await expect(page.getByText(/자료 관측일/).first()).toBeVisible();
  await expect(page.getByText(/효력 기간/).first()).toBeVisible();
  await expect(page.getByText(/2025\. 12\. 31\./).first()).toBeVisible();
  await page.getByRole("button", { name: "공개 문서 새로고침" }).click();
  revision = 2;
  await page.getByRole("button", { name: "공개 문서 새로고침" }).click();
  await expect(
    page.getByText("합성 검증 자료 v2", { exact: true }),
  ).toBeVisible();
  await page
    .locator("#person-intro")
    .getByRole("button", { name: /근거 1/ })
    .click();
  await expect(
    page.getByRole("heading", { name: evidence.title }),
  ).toBeVisible();
  await page.getByRole("button", { name: "뒤로", exact: true }).click();
  await expect(
    page.getByText("합성 검증 자료 v2", { exact: true }),
  ).toBeVisible();
});

for (const width of [360, 412]) {
  test(`${width}px 큰 글자에서 연결 → 법안 원안·대안 → 근거 → 뒤로 이동한다`, async ({
    page,
  }) => {
    const requests: string[] = [];
    page.on("request", (request) => {
      if (request.url().startsWith("https://records.example.org/")) {
        requests.push(request.method() + " " + new URL(request.url()).pathname);
      }
    });
    await setup(page);
    await page.setViewportSize({ width, height: 915 });
    await page.goto(`/#person/${person.id}`);
    await page.getByRole("tab", { name: "연결", exact: true }).click();
    await page
      .getByRole("button", { name: `${bill.title} 연결 보기`, exact: true })
      .click();
    await expect(
      page.getByRole("heading", { name: bill.title, exact: true }),
    ).toBeVisible();
    await page.screenshot({
      path: `artifacts/public-bill-${width}.png`,
      fullPage: true,
    });
    await expect(
      page.getByText("대안 반영은 원안의 독립적인 통과를 뜻하지 않아요.", {
        exact: true,
      }),
    ).toBeVisible();
    await page
      .getByRole("button", { name: "원안·대안 근거 1", exact: true })
      .click();
    await expect(
      page.getByRole("heading", { name: evidence.title }),
    ).toBeVisible();
    await page.getByRole("button", { name: "뒤로", exact: true }).click();
    await page
      .getByRole("button", {
        name: `${alternative.title} 법안 보기`,
        exact: true,
      })
      .click();
    await expect(
      page.getByRole("heading", { name: alternative.title, exact: true }),
    ).toBeVisible();
    await expect(
      page.getByText("이 대안에 연결된 원안", { exact: true }),
    ).toBeVisible();
    await page.getByRole("button", { name: "뒤로", exact: true }).click();
    await page.getByRole("button", { name: "뒤로", exact: true }).click();
    await expect(
      page.getByRole("tab", { name: "연결", exact: true }),
    ).toHaveAttribute("aria-selected", "true");
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    expect(
      requests.every((request) => request.startsWith("GET /api/v1/")),
    ).toBe(true);
    expect(
      requests.some((request) => /admin|sqlite|graphrag/i.test(request)),
    ).toBe(false);
  });
}

test("시간순 이력의 다음 페이지 실패 뒤에도 앞 기록과 조건을 유지한다", async ({
  page,
}) => {
  let fail = true;
  await setup(page, (path, url) =>
    path.endsWith("/timeline")
      ? url.searchParams.has("cursor")
        ? fail
          ? 503
          : {
              id: person.id,
              items: [
                {
                  ...context,
                  eventId: "event_second",
                  activity: {
                    ...activity,
                    id: "event_second",
                    title: "두 번째 공개 합성 기록",
                  },
                },
              ],
              nextCursor: null,
            }
        : { id: person.id, items: [context], nextCursor: "page2" }
      : undefined,
  );
  await page.goto(`/#person/${person.id}`);
  await page.getByRole("tab", { name: "활동", exact: true }).click();
  await page.getByRole("button", { name: "이전 기록 더 보기" }).click();
  await expect(
    page.getByText("일부 활동 기록을 불러오지 못했어요", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: activity.title }),
  ).toBeVisible();
  fail = false;
  await page.getByRole("button", { name: "활동 재시도" }).click();
  await expect(
    page.getByRole("heading", { name: "두 번째 공개 합성 기록" }),
  ).toBeVisible();
  await expect(
    page.getByRole("tab", { name: "활동", exact: true }),
  ).toHaveAttribute("aria-selected", "true");
});

test("근거에서 돌아왔다가 다시 열면 새 공개 원문 버전을 재확인한다", async ({
  page,
}) => {
  let revision = 1;
  await setup(page, (path) =>
    path === `/api/v1/evidence/${evidence.id}`
      ? { ...evidence, documentVersion: `source-v${revision}` }
      : undefined,
  );
  await page.goto(`/#person/${person.id}`);
  await page
    .locator("#person-intro")
    .getByRole("button", { name: /근거 1/ })
    .click();
  await page.getByText("출처와 버전 확인", { exact: true }).click();
  await expect(page.getByText("source-v1", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "뒤로", exact: true }).click();
  revision = 2;
  await page
    .locator("#person-intro")
    .getByRole("button", { name: /근거 1/ })
    .click();
  await page.getByText("출처와 버전 확인", { exact: true }).click();
  await expect(page.getByText("source-v2", { exact: true })).toBeVisible();
});

test("추가 근거를 펼친 뒤 근거 4에서 같은 버튼으로 돌아온다", async ({
  page,
}) => {
  const ids = [evidence.id, "ev_extra2", "ev_extra3", "ev_extra4"];
  await setup(page, (path) =>
    path.endsWith("/profile")
      ? {
          ...profile,
          facts: [{ ...profile.facts[0], evidenceIds: ids }],
        }
      : path === "/api/v1/evidence/ev_extra4"
        ? { ...evidence, id: "ev_extra4" }
        : undefined,
  );
  await page.goto(`/#person/${person.id}`);
  const intro = page.locator("#person-intro");
  await intro.getByText("근거 1개 더 보기", { exact: true }).click();
  await intro.getByRole("button", { name: "근거 4", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: evidence.title }),
  ).toBeVisible();
  await page.getByRole("button", { name: "뒤로", exact: true }).click();
  await expect(
    intro.getByRole("button", { name: "근거 4", exact: true }),
  ).toBeVisible();
  await expect(
    intro.getByRole("button", { name: "근거 4", exact: true }),
  ).toBeFocused();
});

test("11번째 승인 관계의 근거에서 표시 개수와 읽던 위치로 돌아온다", async ({
  page,
}) => {
  const items = Array.from({ length: 11 }, (_, i) => ({
    ...lineage.items[0],
    id: `relation_${i}`,
    reason: `검증 관계 ${i + 1}`,
  }));
  await setup(page, (path) =>
    path === `/api/v1/bills/${bill.id}/lineage`
      ? { ...lineage, items }
      : undefined,
  );
  await page.goto(`/#bill/${bill.id}`);
  await page.getByRole("button", { name: "승인된 관계 더 보기" }).click();
  const last = page
    .locator(".bill-relation")
    .nth(10)
    .getByRole("button", { name: "원안·대안 근거 1", exact: true });
  await last.click();
  await expect(
    page.getByRole("heading", { name: evidence.title }),
  ).toBeVisible();
  await page.getByRole("button", { name: "뒤로", exact: true }).click();
  await expect(page.locator(".bill-relation")).toHaveCount(11);
  await expect(last).toBeInViewport();
  await expect(last).toBeFocused();
});

test("돌아온 문서가 공개 철회되어 짧아져도 다음 이동의 복귀를 막지 않는다", async ({
  page,
}) => {
  let withdrawn = false;
  await setup(page, (path) =>
    path.endsWith("/profile")
      ? withdrawn
        ? 404
        : {
            ...profile,
            facts: Array.from({ length: 18 }, (_, i) => ({
              ...profile.facts[0],
              label: `소개 ${i + 1}`,
            })),
          }
      : undefined,
  );
  await page.goto(`/#person/${person.id}`);
  await page
    .locator("#person-intro .person-fact")
    .last()
    .getByRole("button", { name: "근거 1", exact: true })
    .click();
  withdrawn = true;
  await page.getByRole("button", { name: "뒤로", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "공개된 인물 문서가 없어요" }),
  ).toBeVisible();
  const entryId = await page.evaluate(() => history.state.reader.id);
  await page
    .getByRole("button", { name: "의정의 흐름 홈", exact: true })
    .click();
  await expect
    .poll(() =>
      page.evaluate(
        (id) =>
          JSON.parse(sessionStorage.getItem(`parliament-reader:${id}`) || "{}")
            .y,
        entryId,
      ),
    )
    .toBe(0);
});

for (const [route, path, notFound, failed] of [
  [
    `person/${person.id}`,
    `/api/v1/people/${person.id}/profile`,
    "공개된 인물 문서가 없어요",
    "인물 자료를 불러오지 못했어요",
  ],
  [
    `evidence/${evidence.id}`,
    `/api/v1/evidence/${evidence.id}`,
    "공개된 근거가 없어요",
    "근거를 불러오지 못했어요",
  ],
  [
    `connections/${person.id}`,
    "/api/v1/knowledge/graph",
    "공개된 연결 자료가 없어요",
    "연결 자료를 불러오지 못했어요",
  ],
  [
    `bill/${bill.id}`,
    `/api/v1/bills/${bill.id}`,
    "공개된 법안 문서를 찾지 못했어요",
    "법안을 불러오지 못했어요",
  ],
  [
    `bill/${bill.id}`,
    `/api/v1/bills/${bill.id}/lineage`,
    "공개된 원안·대안 관계 경로를 찾지 못했어요",
    "원안·대안 관계를 불러오지 못했어요",
  ],
] as const) {
  for (const status of [404, 503]) {
    test(`${route} ${path}의 ${status}를 구분한다`, async ({ page }) => {
      await setup(page, (pathname) => (pathname === path ? status : undefined));
      await page.goto(`/#${route}`);
      await expect(
        page.getByText(status === 404 ? notFound : failed, { exact: true }),
      ).toBeVisible();
    });
  }
}
for (const [response, label] of [
  [404, "공개된 인물·문맥 자료를 찾지 못했어요."],
  [503, "인물·문맥 연결을 불러오지 못했어요."],
  [
    { ...context, evidence: [], participants: [] },
    "현재 공개 범위에 인물·문맥 연결이 없어요.",
  ],
] as const) {
  test(`기록 문맥 상태 ${label}`, async ({ page }) => {
    await setup(page, (path) =>
      path.endsWith("/context") ? response : undefined,
    );
    await page.goto(`/#activity/${activity.id}`);
    await expect(page.getByText(label, { exact: true })).toBeVisible();
  });
}

test("느린 공개 본문을 다시 읽은 뒤 이름을 눌렀던 위치로 복귀한다", async ({
  page,
}) => {
  const prefix = "공개 원문 검증을 위한 합성 배경 문장입니다. ".repeat(150);
  const start = Array.from(prefix).length;
  const excerpt = prefix + person.name;
  const longEvidence = {
    ...evidence,
    excerpt,
    end: Array.from(excerpt).length,
    mentions: [
      { ...evidence.mentions[0], start, end: Array.from(excerpt).length },
    ],
  };
  await setup(page, (path) =>
    path.endsWith("/context")
      ? { ...context, evidence: [longEvidence] }
      : undefined,
  );
  let reads = 0;
  await page.route(
    `https://records.example.org/api/v1/activities/${activity.id}`,
    async (route) => {
      if (++reads > 1) await new Promise((resolve) => setTimeout(resolve, 350));
      await route.fulfill({ json: activity });
    },
  );
  await page.goto(`/#activity/${activity.id}`);
  const mention = page.getByRole("button", {
    name: `${person.name} 인물 미리보기`,
    exact: true,
  });
  await mention.scrollIntoViewIfNeeded();
  const before = await page.evaluate(() => scrollY);
  expect(before).toBeGreaterThan(1000);
  await mention.click();
  await page
    .getByRole("button", { name: "인물 전체 보기", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: person.name, exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "뒤로", exact: true }).click();
  await expect(mention).toBeVisible();
  await expect
    .poll(async () => Math.abs((await page.evaluate(() => scrollY)) - before))
    .toBeLessThan(6);
  await expect(mention).toBeFocused();
});
