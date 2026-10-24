import { describe, expect, it, vi } from "vitest";
import { forwardApi } from "@/lib/proxy";
describe("same-origin API proxy", () => {
  it("rejects query overrides on the public issue reading before fetching", async () => {
    const fetcher = vi.fn(async () => Response.json({}));
    const response = await forwardApi(new Request("http://localhost:3000/api/v1/issues/test-issue/reading?state=draft"), ["v1", "issues", "test-issue", "reading"], fetcher);
    expect(response.status).toBe(400);
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("keeps issue reading read-only and preserves conflicts without forwarding session credentials", async () => {
    const response = await forwardApi(new Request("http://localhost:3000/api/v1/issues/test-issue/reading", {
      headers: { Cookie: "private=session", "X-CSRF-Token": "private-token", "X-Admin-Key": "private-admin" },
    }), ["v1", "issues", "test-issue", "reading"], async (_url, init) => {
      const headers = new Headers(init?.headers);
      expect(init?.method).toBe("GET");
      expect(headers.get("cookie")).toBeNull();
      expect(headers.get("x-csrf-token")).toBeNull();
      expect(headers.get("x-admin-key")).toBeNull();
      return Response.json({ error: "reading_version_conflict" }, { status: 409, headers: { "Set-Cookie": "private=session" } });
    });
    expect(response.status).toBe(409);
    expect(response.headers.get("Set-Cookie")).toBeNull();
    expect(response.headers.get("Cache-Control")).toBe("no-store");
  });
  it("rejects administrative paths before any upstream request", async () => {
    const response = await forwardApi(new Request("http://localhost:3000/api/admin"), ["admin"], async () => { throw new Error("must not fetch"); });
    expect(response.status).toBe(404);
  });
  it("rejects cross-origin changes before forwarding a cookie", async () => {
    const response = await forwardApi(new Request("http://localhost:3000/api/v1/me/follows", { method: "PUT", headers: { Origin: "https://evil.test" }, body: "{}" }), ["v1", "me", "follows"]);
    expect(response.status).toBe(403);
  });
  it("forwards authenticated cookies and CSRF without leaking an upstream key", async () => {
    const response = await forwardApi(new Request("http://localhost:3000/api/v1/me/follows", { method: "PUT", headers: { Origin: "http://localhost:3000", Cookie: "parliament_session=test", "X-CSRF-Token": "csrf", "X-Admin-Key": "do-not-pass" }, body: '{"follows":[]}' }), ["v1", "me", "follows"], async (_url, init) => {
      const headers = new Headers(init?.headers);
      expect(headers.get("cookie")).toBe("parliament_session=test");
      expect(headers.get("x-csrf-token")).toBe("csrf");
      expect(headers.get("x-admin-key")).toBeNull();
      return new Response('{"ok":true}', { headers: { "content-type": "application/json", "set-cookie": "parliament_session=new; HttpOnly; Path=/" } });
    });
    expect(response.status).toBe(200);
    expect(response.headers.get("set-cookie")).toContain("HttpOnly");
  });
  it("returns a retryable error when the upstream is offline", async () => {
    const response = await forwardApi(new Request("http://localhost:3000/api/v1/activities"), ["v1", "activities"], async () => { throw new Error("secret address"); });
    expect(response.status).toBe(503);
    expect(await response.text()).not.toContain("secret address");
  });
});

describe("digest unsubscribe boundary", () => {
  it("accepts only same-origin POST unsubscribe tokens", async () => {
    const response = await forwardApi(new Request("http://localhost:3000/api/v1/auth/unsubscribe", { method: "POST", headers: { Origin: "http://localhost:3000" }, body: '{"token":"one-time-token"}' }), ["v1", "auth", "unsubscribe"], async () => new Response(null, { status: 204 }));
    expect(response.status).toBe(204);
  });
});

describe("optional first-party metrics boundary", () => {
  it("forwards the usage endpoint with same-origin protections", async () => {
    const response = await forwardApi(new Request("http://localhost:3000/api/v1/usage", { method: "POST", headers: { Origin: "http://localhost:3000", "X-CSRF-Token": "csrf" }, body: '{"event":"activity_opened"}' }), ["v1", "usage"], async () => new Response(null, { status: 202 }));
    expect(response.status).toBe(202);
  });
});

function streamingRequest(chunks: Uint8Array[], headers: Record<string, string> = {}) {
  let pulled = 0;
  const cancel = vi.fn();
  const stream = new ReadableStream<Uint8Array>({
    pull(controller) {
      if (pulled < chunks.length) controller.enqueue(chunks[pulled++]);
      else controller.close();
    },
    cancel
  }, { highWaterMark: 0 });
  const init: RequestInit & { duplex: "half" } = {
    method: "POST", headers: { Origin: "http://localhost:3000", ...headers }, body: stream, duplex: "half"
  };
  return { request: new Request("http://localhost:3000/api/v1/auth/request-link", init), cancel, pulled: () => pulled };
}

describe("bounded request streams", () => {
  const lengthHeaders: Record<string, string>[] = [{}, { "Content-Length": "2" }];
  it.each(lengthHeaders)("cancels oversized streams before draining or fetching with headers %j", async headers => {
    const incoming = streamingRequest([
      new Uint8Array(16384), new Uint8Array(16384), new Uint8Array(1), new Uint8Array(1024)
    ], headers);
    const fetcher = vi.fn(async () => new Response(null, { status: 202 }));
    const response = await forwardApi(incoming.request, ["v1", "auth", "request-link"], fetcher);
    expect(response.status).toBe(413);
    expect(incoming.cancel).toHaveBeenCalledOnce();
    expect(incoming.pulled()).toBe(3);
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("preserves UTF8 split across chunks at the exact byte limit", async () => {
    const body = "가".repeat(10922) + "ab";
    const bytes = new TextEncoder().encode(body);
    expect(bytes.byteLength).toBe(32768);
    const incoming = streamingRequest([bytes.slice(0, 1), bytes.slice(1, 16384), bytes.slice(16384)]);
    const fetcher = vi.fn(async (_url: unknown, init?: RequestInit) => {
      expect(init?.body).toBe(body);
      return new Response(null, { status: 202 });
    });
    expect((await forwardApi(incoming.request, ["v1", "auth", "request-link"], fetcher)).status).toBe(202);
    expect(fetcher).toHaveBeenCalledOnce();
    expect(incoming.cancel).not.toHaveBeenCalled();
  });

  it("enforces UTF8 bytes rather than string length", async () => {
    const bytes = new TextEncoder().encode("가".repeat(11000));
    const incoming = streamingRequest([bytes.slice(0, 32768), bytes.slice(32768), new Uint8Array(1)]);
    const fetcher = vi.fn(async () => new Response(null, { status: 202 }));
    expect((await forwardApi(incoming.request, ["v1", "auth", "request-link"], fetcher)).status).toBe(413);
    expect(incoming.cancel).toHaveBeenCalledOnce();
    expect(incoming.pulled()).toBe(2);
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("keeps the declared length precheck before reading the stream", async () => {
    const incoming = streamingRequest([new Uint8Array(1)], { "Content-Length": "32769" });
    const fetcher = vi.fn(async () => new Response(null, { status: 202 }));
    expect((await forwardApi(incoming.request, ["v1", "auth", "request-link"], fetcher)).status).toBe(413);
    expect(incoming.pulled()).toBe(0);
    expect(incoming.cancel).toHaveBeenCalledOnce();
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("returns 413 even when the sender never completes cancellation", async () => {
    const incoming = streamingRequest([new Uint8Array(32769)]);
    incoming.cancel.mockImplementation(() => new Promise<void>(() => {}));
    const fetcher = vi.fn(async () => new Response(null, { status: 202 }));
    expect((await forwardApi(incoming.request, ["v1", "auth", "request-link"], fetcher)).status).toBe(413);
    expect(incoming.cancel).toHaveBeenCalledOnce();
    expect(fetcher).not.toHaveBeenCalled();
  });

  it.each([
    { path: ["admin"], origin: "http://localhost:3000", status: 404 },
    { path: ["v1", "auth", "request-link"], origin: "https://evil.test", status: 403 }
  ])("checks path and origin before reading (%s)", async ({ path, origin, status }) => {
    const incoming = streamingRequest([new Uint8Array(1)], { Origin: origin });
    const fetcher = vi.fn(async () => new Response(null, { status: 202 }));
    expect((await forwardApi(incoming.request, path, fetcher)).status).toBe(status);
    expect(incoming.pulled()).toBe(0);
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("preserves bodyless logout requests", async () => {
    const request = new Request("http://localhost:3000/api/v1/auth/logout", {
      method: "POST", headers: { Origin: "http://localhost:3000", "X-CSRF-Token": "csrf" }
    });
    expect(request.body).toBeNull();
    const response = await forwardApi(request, ["v1", "auth", "logout"], async (_url, init) => {
      expect(init?.body).toBe("");
      return new Response(null, { status: 204 });
    });
    expect(response.status).toBe(204);
  });
});
