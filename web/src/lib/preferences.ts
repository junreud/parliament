import type { Activity, Follow, Preferences } from "./contracts";
export const STORAGE_KEY = "parliament.interests.v1";
export const EMPTY_PREFERENCES: Preferences = { follows: [], frequency: "weekly" };
export function parsePreferences(value: string | null): Preferences {
  try {
    const parsed = JSON.parse(value || "{}");
    const follows: Follow[] = [];
    for (const entry of Array.isArray(parsed.follows) ? parsed.follows : []) {
      if (["person", "topic", "bill", "issue"].includes(entry?.kind) && typeof entry?.targetId === "string" && /^[A-Za-z0-9_-]{1,128}$/.test(entry.targetId)) {
        const follow = { kind: entry.kind, targetId: entry.targetId } as Follow;
        if (!follows.some(item => item.kind === follow.kind && item.targetId === follow.targetId)) follows.push(follow);
      }
      if (follows.length >= 20) break;
    }
    return { follows, frequency: ["daily", "weekly", "off"].includes(parsed.frequency) ? parsed.frequency : "weekly" };
  } catch { return { ...EMPTY_PREFERENCES, follows: [] }; }
}
export function toggleFollow(follows: Follow[], follow: Follow): Follow[] {
  const exists = follows.some(item => item.kind === follow.kind && item.targetId === follow.targetId);
  return exists ? follows.filter(item => item.kind !== follow.kind || item.targetId !== follow.targetId) : [...follows, follow];
}
export function matchesFollows(activity: Pick<Activity, "personIds" | "topics" | "billId">, follows: Follow[]): boolean {
  return follows.some(follow => follow.kind === "person" ? activity.personIds.includes(follow.targetId) : follow.kind === "topic" ? activity.topics.includes(follow.targetId) : follow.kind === "bill" ? activity.billId === follow.targetId : activity.topics.includes(follow.targetId));
}
