export const BETA_SOURCES = ["instagram", "network", "community", "direct"] as const;
export type BetaSource = typeof BETA_SOURCES[number];
export type BetaVisitKind = "organic" | "research";
export type BetaEvent = "explainer_opened" | "source_opened" | "timeline_opened";
export type BetaSession = { participating: false } | { participating: true; csrfToken: string };
export function normalizeBetaSource(params: URLSearchParams): BetaSource {
  const source = params.get("utm_source");
  return BETA_SOURCES.includes(source as BetaSource) ? source as BetaSource : "direct";
}
export function betaVisitKind(params: URLSearchParams): BetaVisitKind {
  return params.get("visit") === "research" ? "research" : "organic";
}
export const BETA_VISIT_CONTEXT_KEY = "beta-visit-context";
const RESEARCH_VISIT_MS = 30 * 60 * 1000;
type BetaVisitStorage = Pick<Storage, "getItem" | "setItem" | "removeItem">;
export function resolveBetaVisitKind(params: URLSearchParams, storage: BetaVisitStorage, now = Date.now()): BetaVisitKind {
  if (betaVisitKind(params) === "research") {
    storage.setItem(BETA_VISIT_CONTEXT_KEY, JSON.stringify({ visitKind: "research", until: now + RESEARCH_VISIT_MS }));
    return "research";
  }
  const raw = storage.getItem(BETA_VISIT_CONTEXT_KEY);
  if (!raw) return "organic";
  try {
    const context: unknown = JSON.parse(raw);
    if (context && typeof context === "object") {
      const value = context as Record<string, unknown>;
      if (Object.keys(value).length === 2 && value.visitKind === "research" && typeof value.until === "number" &&
        Number.isFinite(value.until) && value.until > now && value.until <= now + RESEARCH_VISIT_MS) return "research";
    }
  } catch { /* Discard malformed context rather than extending a research visit. */ }
  storage.removeItem(BETA_VISIT_CONTEXT_KEY);
  return "organic";
}
export function isBetaSession(value: unknown): value is BetaSession {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Record<string, unknown>;
  return candidate.participating === false || candidate.participating === true &&
    typeof candidate.csrfToken === "string" && candidate.csrfToken.length > 0 && candidate.csrfToken.length <= 512;
}
export async function sendBetaEvent(session: BetaSession, event: BetaEvent, visitKind: BetaVisitKind, fetcher: typeof fetch = fetch): Promise<void> {
  if (!session.participating) return;
  try {
    await fetcher("/api/v1/beta/events", {
      method: "POST", referrerPolicy: "no-referrer", credentials: "same-origin", cache: "no-store",
      headers: { "Content-Type": "application/json", "x-csrf-token": session.csrfToken },
      body: JSON.stringify({ event, visitKind }), signal: AbortSignal.timeout(5000), keepalive: true
    });
  } catch { /* Research measurement must not interrupt public reading. */ }
}
