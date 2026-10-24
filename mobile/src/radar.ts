import { transport, type Result, type Transport } from "./api";
import { normalizeOrigin } from "./state";
import { isRadarPage, type RadarPage } from "../../web/src/lib/radar";
export async function readRadar(
  origin: string,
  request: Transport = transport,
): Promise<Result<RadarPage>> {
  const base = normalizeOrigin(origin);
  if (!base) return { status: "error" };
  try {
    const response = await request(new URL("/api/v1/radar", base).href);
    if (response.status === 404) return { status: "not-found" };
    return response.status === 200 && isRadarPage(response.data)
      ? { status: "ok", data: response.data }
      : { status: "error" };
  } catch {
    return { status: "error" };
  }
}
