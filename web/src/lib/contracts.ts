export interface Evidence {
  id: string;
  sourceUrl: string;
  excerpt: string | null;
  locator: string;
  sourceVersion: string;
}
export interface Vote { personId: string; name: string; result: string; sessionId: string; }
export interface Activity {
  id: string; type: string; title: string; summary: string | null; stage: string;
  personIds: string[]; topics: string[]; billId: string | null;
  occurredAt: string | null; publishedAt: string; collectedAt: string; changedAt?: string;
  sourceUrl: string; evidence: Evidence[]; votes: Vote[];
  coverage: string; corrected: boolean; version: string;
}
export interface Page<T> { items: T[]; nextCursor?: string | null; }
export interface Person { id: string; name: string; kind: string; organization: string; role: string; activities?: Activity[]; }
export interface Bill { id: string; title: string; stage: string; activities?: Activity[]; votes?: Vote[]; sourceUrl?: string; }
export interface Issue { id: string; title: string; topic: string; description: string; activities?: Activity[]; }
export interface ActivityVersion { version: string; reviewedAt: string; correctionReason: string | null; corrected: boolean; }
export interface Coverage { source: string; status: string; lastObservedAt: string | null; range: string; note: string; }
export type FollowKind = "person" | "topic" | "bill" | "issue";
export interface Follow { kind: FollowKind; targetId: string; }
export interface Preferences { follows: Follow[]; frequency: "daily" | "weekly" | "off"; }
export interface Session extends Preferences { authenticated: boolean; csrfToken?: string; }
export type ApiResult<T> = { status: "ok"; data: T } | { status: "offline" } | { status: "not-found" };
