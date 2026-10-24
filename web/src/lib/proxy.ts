import { backendUrl, isAllowedProxyPath } from "./api";
const MAX_REQUEST_BYTES = 32768;
function error(status: number, message: string): Response {
  return Response.json({ message }, { status, headers: { "Cache-Control": "no-store" } });
}
async function readBoundedBody(request: Request): Promise<string | null> {
  if (!request.body) return "";
  const reader = request.body.getReader();
  const bytes = new Uint8Array(MAX_REQUEST_BYTES);
  let length = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) return new TextDecoder().decode(bytes.subarray(0, length));
      if (value.byteLength > MAX_REQUEST_BYTES - length) {
        // Do not await a disconnected client's cancellation before returning 413.
        void reader.cancel().catch(() => {});
        return null;
      }
      bytes.set(value, length);
      length += value.byteLength;
    }
  } finally {
    reader.releaseLock();
  }
}
export async function forwardApi(request: Request, path: string[], fetcher: typeof fetch = fetch): Promise<Response> {
  if (!isAllowedProxyPath(path, request.method)) return error(404, "지원하지 않는 요청입니다.");
  const current = new URL(request.url);
  const publicReading = path.length === 4 && path[1] === "issues" && path[3] === "reading";
  if (publicReading && current.search) return error(400, "지원하지 않는 해설 요청입니다.");
  if (request.method !== "GET") {
    const allowedOrigin = process.env.PUBLIC_BASE_URL || current.origin;
    if (request.headers.get("origin") !== allowedOrigin) return error(403, "같은 사이트에서 요청해 주세요.");
    if (Number(request.headers.get("content-length") || 0) > MAX_REQUEST_BYTES) {
      void request.body?.cancel().catch(() => {});
      return error(413, "요청이 너무 큽니다.");
    }
  }
  try {
    const headers = new Headers({ Accept: "application/json" });
    for (const name of publicReading ? [] : ["cookie", "x-csrf-token", "origin"]) {
      const value = request.headers.get(name);
      if (value) headers.set(name, value);
    }
    let body: string | undefined;
    if (request.method !== "GET") {
      const boundedBody = await readBoundedBody(request);
      if (boundedBody === null) return error(413, "요청이 너무 큽니다.");
      body = boundedBody;
      headers.set("Content-Type", "application/json");
    }
    const upstream = await fetcher(backendUrl(`/api/${path.join("/")}${current.search}`), {
      method: request.method, headers, body, redirect: "manual", cache: "no-store", signal: AbortSignal.timeout(10000)
    });
    if (upstream.status >= 300 && upstream.status < 400) return error(502, "요청을 처리할 수 없습니다.");
    const responseHeaders = new Headers({ "Content-Type": "application/json", "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" });
    if (!publicReading) for (const cookie of upstream.headers.getSetCookie()) responseHeaders.append("Set-Cookie", cookie);
    return new Response(upstream.body, { status: upstream.status, headers: responseHeaders });
  } catch { return error(503, "기록 서버에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요."); }
}
