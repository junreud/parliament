import { isRadarPage } from "./radar";
import type { ApiResult } from "./contracts";
import { isApiPayload } from "./validation";
import { isEntityId, isKnowledgePayload } from "./knowledge-validation";
import { isGraphPayload } from "./graph-validation";
const READ_COLLECTIONS = ["activities", "people", "bills", "issues", "search", "coverage", "laws", "radar"];
export function isAllowedProxyPath(path: string[], method: string): boolean {
  if (path[0] !== "v1" || path.some(segment => !/^[a-zA-Z0-9_.:-]{1,128}$/.test(segment) || segment === "." || segment === "..")) return false;
  if (path.length >= 3 && ["activities", "people", "bills", "issues", "documents", "evidence"].includes(path[1]) && !isEntityId(path[2])) return false;
  if (method === "GET") return (path.join("/") === "v1/beta/session") || (path.length === 3 && path[1] === "knowledge" && ["graph", "people"].includes(path[2])) ||
    (path.length === 2 && [...READ_COLLECTIONS, "me"].includes(path[1])) ||
    (path.length === 3 && ["activities", "people", "bills", "issues", "documents", "evidence"].includes(path[1])) ||
    (path.length === 4 && ((path[1] === "activities" && ["history", "context"].includes(path[3])) || (path[1] === "people" && ["profile", "timeline"].includes(path[3])) || (path[1] === "bills" && path[3] === "lineage") || (path[1] === "issues" && ["timeline", "reading"].includes(path[3]))));
  if (method === "PUT") return path.join("/") === "v1/me/follows";
  if (method === "POST") return ["v1/beta/participants", "v1/beta/events", "v1/beta/acquisition", "v1/beta/withdraw", "v1/usage", "v1/auth/request-link", "v1/auth/verify", "v1/auth/logout", "v1/auth/unsubscribe"].includes(path.join("/"));
  return false;
}
export function backendUrl(path: string, base = process.env.BACKEND_URL || "http://localhost:8080"): URL {
  if (!path.startsWith("/api/v1/") || /[\\#]/.test(path)) throw new Error("Invalid API path");
  const pathname = path.split("?")[0];
  if (!isAllowedProxyPath(pathname.slice(5).split("/"), "GET") && !isAllowedProxyPath(pathname.slice(5).split("/"), "POST") && !isAllowedProxyPath(pathname.slice(5).split("/"), "PUT")) throw new Error("Unsupported API path");
  const origin = new URL(base);
  if (!["http:", "https:"].includes(origin.protocol) || origin.username || origin.password || origin.pathname !== "/" || origin.search || origin.hash) throw new Error("Invalid backend origin");
  return new URL(path, origin);
}
export async function readApi<T>(path: string, fetcher: typeof fetch = fetch): Promise<ApiResult<T>> {
  try {
    const response = await fetcher(backendUrl(path), { cache: "no-store", signal: AbortSignal.timeout(5000), headers: { Accept: "application/json" } });
    if (response.status === 404) return { status: "not-found" };
    if (!response.ok) return { status: "offline" };
    const data = await response.json() as T;
    if (!(path === "/api/v1/radar" ? isRadarPage(data) : isGraphPayload(path, data) ?? isKnowledgePayload(path, data) ?? isApiPayload(path, data))) return { status: "offline" };
    return { status: "ok", data };
  } catch { return { status: "offline" }; }
}
