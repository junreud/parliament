import { createServer } from "node:http";
import { pathToFileURL } from "node:url";

// Local development gateway for the Galaxy app. The upstream is fixed and only
// public GET paths are exposed; never tunnel the Spring admin server directly.
const UPSTREAM = "http://127.0.0.1:8080";
const ORIGINS = new Set([
  "http://127.0.0.1:14200",
  "http://localhost:14200",
  "https://localhost",
]);
const MAX_BYTES = 2 * 1024 * 1024;
const ID = "[A-Za-z0-9_-]{1,128}";
const RULES = [
  [
    /^\/api\/v1\/knowledge\/people$/,
    ["cursor", "query", "organizationId", "limit"],
  ],
  [
    /^\/api\/v1\/knowledge\/graph$/,
    ["rootId", "rootKind", "depth", "limit", "relationType"],
  ],
  [new RegExp(`^/api/v1/people/${ID}/profile$`), []],
  [
    new RegExp(`^/api/v1/people/${ID}/timeline$`),
    ["cursor", "limit", "order", "from", "until", "role"],
  ],
  [new RegExp(`^/api/v1/evidence/${ID}$`), []],
  [new RegExp(`^/api/v1/bills/${ID}(?:/lineage)?$`), []],
  [new RegExp(`^/api/v1/issues/${ID}/reading$`), []],
  [
    /^\/api\/v1\/(activities|search)$/,
    ["cursor", "limit", "topic", "type", "q", "personId", "billId", "issueId"],
  ],
  [
    /^\/api\/v1\/activities\/[A-Za-z0-9_.:-]{1,128}(?:\/context)?$/,
    ["version"],
  ],
  [/^\/api\/v1\/(coverage|laws|radar)$/, ["limit", "cursor", "query"]],
];
async function boundedJson(response) {
  if (!response.body) throw new Error("missing response");
  const reader = response.body.getReader();
  const chunks = [];
  let size = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > MAX_BYTES) throw new Error("response too large");
      chunks.push(Buffer.from(value));
    }
    return JSON.parse(Buffer.concat(chunks).toString("utf8"));
  } finally {
    await reader.cancel().catch(() => {});
  }
}
export function createPublicGateway(fetcher = fetch) {
  let active = 0;
  const server = createServer(async (request, response) => {
    const headers = {
      "Content-Type": "application/json",
      "Cache-Control": "no-store",
      "X-Content-Type-Options": "nosniff",
      Vary: "Origin",
    };
    const send = (status, payload) => {
      response.writeHead(status, headers);
      response.end(status === 204 ? undefined : JSON.stringify(payload));
    };
    const origin = request.headers.origin;
    if (origin && !ORIGINS.has(origin))
      return send(403, { error: "origin_not_allowed" });
    if (origin) headers["Access-Control-Allow-Origin"] = origin;
    const raw = request.url || "";
    if (
      !raw.startsWith("/") ||
      raw.startsWith("//") ||
      raw.length > 4000 ||
      /[#\\]/.test(raw)
    )
      return send(404, { error: "not_found" });
    const url = new URL(raw, UPSTREAM);
    const rule = RULES.find(([path]) => path.test(url.pathname));
    if (!rule) return send(404, { error: "not_found" });
    if (request.method === "OPTIONS") {
      if (request.headers["access-control-request-method"] !== "GET")
        return send(405, { error: "read_only" });
      const requested = String(
        request.headers["access-control-request-headers"] || "",
      )
        .toLowerCase()
        .split(",")
        .map((item) => item.trim())
        .filter(Boolean);
      if (requested.some((name) => name !== "accept"))
        return send(403, { error: "headers_not_allowed" });
      headers["Access-Control-Allow-Methods"] = "GET";
      headers["Access-Control-Allow-Headers"] = "Accept";
      return send(204);
    }
    if (request.method !== "GET") return send(405, { error: "read_only" });
    const keys = [...url.searchParams.keys()];
    if (
      keys.some((key) => !rule[1].includes(key)) ||
      new Set(keys).size !== keys.length
    )
      return send(400, { error: "invalid_query" });
    if (active >= 16) return send(503, { error: "public_api_unavailable" });
    active++;
    try {
      const upstream = await fetcher(url.href, {
        method: "GET",
        headers: { Accept: "application/json" },
        redirect: "error",
        credentials: "omit",
        cache: "no-store",
        signal: AbortSignal.timeout(8000),
      });
      if (upstream.status >= 300 && upstream.status < 400)
        throw new Error("redirect refused");
      const payload = await boundedJson(upstream);
      return send(upstream.status, payload);
    } catch {
      return send(503, { error: "public_api_unavailable" });
    } finally {
      active--;
    }
  });
  server.requestTimeout = 10000;
  server.headersTimeout = 10000;
  server.maxHeadersCount = 32;
  return server;
}
if (
  process.argv[1] &&
  import.meta.url === pathToFileURL(process.argv[1]).href
) {
  const port = Number(process.env.PARLIAMENT_PUBLIC_GATEWAY_PORT || 18081);
  if (!Number.isInteger(port) || port < 1024 || port > 65535)
    throw new Error("Invalid public gateway port");
  createPublicGateway().listen(port, "127.0.0.1");
}
