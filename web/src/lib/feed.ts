import type { Activity, Follow } from "./contracts";
import { isActivity } from "./validation";
function compareTime(first: string, second: string): number {
  const difference = Date.parse(first) - Date.parse(second);
  if (difference !== 0) return difference;
  const fraction = (value: string) => (value.match(/\.(\d+)(?:Z|[+-])/)?.[1] || "").padEnd(9, "0").slice(3, 9);
  return fraction(first).localeCompare(fraction(second));
}
export async function loadFollowFeed(follows: Follow[], fetcher: typeof fetch = fetch): Promise<{ items: Activity[]; status: "ok" | "partial" | "offline" }> {
  const targets = follows.slice(0, 20);
  const pages = await Promise.all(targets.map(async follow => {
    try {
      const query = new URLSearchParams({ [follow.kind === "person" ? "personId" : follow.kind === "bill" ? "billId" : "topic"]: follow.targetId, limit: "20" });
      const path = follow.kind === "issue" ? `/api/v1/issues/${encodeURIComponent(follow.targetId)}` : `/api/v1/activities?${query}`;
      const response = await fetcher(path, { credentials: "same-origin", cache: "no-store", signal: AbortSignal.timeout(10000) });
      if (!response.ok) return null;
      const data = await response.json();
      const items = follow.kind === "issue" ? data.activities : data.items;
      return Array.isArray(items) && items.every(isActivity) ? items.slice(0, 20) as Activity[] : null;
    } catch { return null; }
  }));
  const records = new Map<string, Activity>();
  for (const page of pages) for (const activity of page || []) {
    if (!isActivity(activity)) continue;
    const previous = records.get(activity.id);
    if (!previous || compareTime(activity.changedAt || activity.collectedAt, previous.changedAt || previous.collectedAt) > 0) records.set(activity.id, activity);
  }
  const failures = pages.filter(page => page === null).length;
  return { items: Array.from(records.values()).sort((a, b) => compareTime(b.changedAt || b.collectedAt, a.changedAt || a.collectedAt) || b.id.localeCompare(a.id)), status: failures === 0 ? "ok" : failures === pages.length ? "offline" : "partial" };
}
