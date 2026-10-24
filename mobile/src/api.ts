import { Capacitor, CapacitorHttp } from "@capacitor/core";
import { isApiPayload } from "../../web/src/lib/validation";
import { normalizeOrigin } from "./state";
export type Result<T> =
  { status: "ok"; data: T } | { status: "error" | "not-found" };
export type Transport = (
  url: string,
) => Promise<{ status: number; data: unknown }>;
export const transport: Transport = async (url) => {
  if (Capacitor.isNativePlatform())
    return CapacitorHttp.get({
      url,
      connectTimeout: 8000,
      readTimeout: 8000,
      disableRedirects: true,
      responseType: "json",
      headers: { Accept: "application/json" },
    });
  const response = await fetch(url, {
    credentials: "omit",
    redirect: "error",
    cache: "no-store",
    signal: AbortSignal.timeout(8000),
    headers: { Accept: "application/json" },
  });
  return {
    status: response.status,
    data: response.ok ? await response.json() : null,
  };
};
export async function readRecords<T>(
  origin: string,
  path: string,
  request: Transport = transport,
): Promise<Result<T>> {
  const base = normalizeOrigin(origin);
  if (
    !base ||
    !/^\/api\/v1\/(activities(?:\/[a-zA-Z0-9_.:-]{1,128})?|search|coverage)(\?[^#\\]*)?$/.test(
      path,
    ) ||
    /\/(\.|\.\.)(\?|$)/.test(path)
  )
    return { status: "error" };
  try {
    const response = await request(new URL(path, base).href);
    if (response.status === 404) return { status: "not-found" };
    if (response.status !== 200 || !isApiPayload(path, response.data))
      return { status: "error" };
    return { status: "ok", data: response.data as T };
  } catch {
    return { status: "error" };
  }
}
