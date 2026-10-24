import { test } from "node:test";
import assert from "node:assert/strict";
import { createPublicGateway } from "../scripts/public-gateway.mjs";

async function withGateway(
  run,
  upstream = async () => Response.json({ items: [], nextCursor: null }),
) {
  const calls = [];
  const server = createPublicGateway(async (...args) => {
    calls.push(args);
    return upstream(...args);
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  try {
    await run(`http://127.0.0.1:${server.address().port}`, calls);
  } finally {
    server.closeAllConnections();
    await new Promise((resolve) => server.close(resolve));
  }
}

test("공개 GET만 고정된 로컬 서버로 중계하고 자격 증명을 전달하지 않는다", async () => {
  await withGateway(async (origin, calls) => {
    const response = await fetch(`${origin}/api/v1/knowledge/people?limit=40`, {
      headers: {
        Origin: "http://127.0.0.1:14200",
        Cookie: "private=test",
        Authorization: "Bearer test-only",
      },
    });
    assert.equal(response.status, 200);
    assert.deepEqual(await response.json(), { items: [], nextCursor: null });
    assert.equal(
      response.headers.get("Access-Control-Allow-Origin"),
      "http://127.0.0.1:14200",
    );
    assert.equal(response.headers.get("Cache-Control"), "no-store");
    assert.equal(response.headers.get("Set-Cookie"), null);
    assert.equal(calls.length, 1);
    assert.equal(
      calls[0][0],
      "http://127.0.0.1:8080/api/v1/knowledge/people?limit=40",
    );
    assert.deepEqual(calls[0][1].headers, { Accept: "application/json" });
    assert.equal(calls[0][1].method, "GET");
    assert.equal(calls[0][1].redirect, "error");
  });
});

test("관리자·파일·상대 경로·쓰기·비공개 질의를 서버에 전달하지 않는다", async () => {
  await withGateway(async (origin, calls) => {
    for (const [path, method, expected] of [
      ["/admin/knowledge/batches", "GET", 404],
      ["/.env", "GET", 404],
      ["/private/candidates.sqlite", "GET", 404],
      ["/api/v1/knowledge/people", "POST", 405],
      ["/api/v1/knowledge/people?visibility=candidate", "GET", 400],
      ["/api/v1/knowledge/graph?batchId=private", "GET", 400],
      ["/api/v1/knowledge/people?limit=1&limit=99", "GET", 400],
      ["/api/v1/../admin/knowledge", "GET", 404],
    ])
      assert.equal(
        (await fetch(origin + path, { method })).status,
        expected,
        path,
      );
    assert.equal(calls.length, 0);
  });
});

test("허용된 개발 화면의 GET preflight만 응답한다", async () => {
  await withGateway(async (origin, calls) => {
    const response = await fetch(origin + "/api/v1/knowledge/people", {
      method: "OPTIONS",
      headers: {
        Origin: "https://localhost",
        "Access-Control-Request-Method": "GET",
        "Access-Control-Request-Headers": "accept",
      },
    });
    assert.equal(response.status, 204);
    assert.equal(
      response.headers.get("Access-Control-Allow-Origin"),
      "https://localhost",
    );
    assert.equal(
      response.headers.get("Access-Control-Allow-Credentials"),
      null,
    );
    assert.equal(
      (
        await fetch(origin + "/api/v1/knowledge/people", {
          headers: { Origin: "https://untrusted.example" },
        })
      ).status,
      403,
    );
    assert.equal(
      (
        await fetch(origin + "/api/v1/knowledge/people", {
          method: "OPTIONS",
          headers: {
            Origin: "http://127.0.0.1:14200",
            "Access-Control-Request-Method": "POST",
          },
        })
      ).status,
      405,
    );
    assert.equal(calls.length, 0);
  });
});

for (const [label, upstream] of [
  [
    "통신 실패",
    async () => {
      throw new Error("private upstream details");
    },
  ],
  [
    "리디렉션",
    async () =>
      new Response("", {
        status: 302,
        headers: { Location: "https://untrusted.example" },
      }),
  ],
  ["JSON 아님", async () => new Response("<html>private details</html>")],
  ["응답 크기 초과", async () => new Response(" ".repeat(2 * 1024 * 1024 + 1))],
])
  test(`${label}를 예시 없는 일반 오류로 처리한다`, async () => {
    await withGateway(async (origin) => {
      const response = await fetch(origin + "/api/v1/knowledge/people");
      assert.equal(response.status, 503);
      assert.deepEqual(await response.json(), {
        error: "public_api_unavailable",
      });
    }, upstream);
  });

test("공개 API의 실제 404·503 상태를 보존한다", async () => {
  for (const status of [404, 503])
    await withGateway(
      async (origin) => {
        const response = await fetch(origin + "/api/v1/evidence/unknown");
        assert.equal(response.status, status);
      },
      async () => Response.json({ error: "not found" }, { status }),
    );
});

test("이슈 해설의 정확한 GET과 400·404·409·503을 보존한다", async () => {
  for (const status of [400, 404, 409, 503])
    await withGateway(
      async (origin, calls) => {
        const response = await fetch(
          origin + "/api/v1/issues/test-issue/reading",
        );
        assert.equal(response.status, status);
        assert.equal(response.headers.get("Cache-Control"), "no-store");
        assert.equal(
          calls[0][0],
          "http://127.0.0.1:8080/api/v1/issues/test-issue/reading",
        );
      },
      async () => Response.json({ error: "contract-test" }, { status }),
    );
});

test("이슈 해설의 비공개 질의·인접 경로·쓰기를 허용하지 않는다", async () => {
  await withGateway(async (origin, calls) => {
    for (const [path, method, status] of [
      ["/api/v1/issues/test-issue/reading?state=draft", "GET", 400],
      ["/api/v1/issues/test-issue/reading?version=private", "GET", 400],
      ["/api/v1/issues/test-issue/publications", "GET", 404],
      ["/api/v1/issues/test-issue/reading/draft", "GET", 404],
      ["/api/v1/issues/test-issue/reading", "POST", 405],
    ])
      assert.equal((await fetch(origin + path, { method })).status, status);
    assert.equal(calls.length, 0);
  });
});
