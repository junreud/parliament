import { transport, type Result, type Transport } from "./api";
import { normalizeOrigin } from "./state";
import { isLawPage, type LawPage } from "../../web/src/lib/law-records";
export { isLawPage, lawSource } from "../../web/src/lib/law-records";
export type { Law, LawEvidence, LawPage } from "../../web/src/lib/law-records";

export async function readLaws(
  origin: string,
  request: Transport = transport,
): Promise<Result<LawPage>> {
  const base = normalizeOrigin(origin);
  if (!base) return { status: "error" };
  try {
    const response = await request(new URL("/api/v1/laws", base).href);
    if (response.status === 404) return { status: "not-found" };
    if (response.status !== 200 || !isLawPage(response.data))
      return { status: "error" };
    return { status: "ok", data: response.data };
  } catch {
    return { status: "error" };
  }
}
export function lawDate(value: string | null): string {
  return value ? value.replaceAll("-", ". ") + "." : "미확인";
}
