/** News metadata is not a verified government decision or a measure of public opinion. */
export interface NewsArticle {
  title: string;
  url: string;
  publisher: string;
  publishedAt: string;
}
export interface RadarItem {
  id: string;
  title: string;
  question: string;
  reason: string;
  score: number;
  articleCount: number;
  publisherCount: number;
  independentSignals: number;
  growth: {
    status: "no-baseline" | "new" | "rising" | "steady";
    recent: number;
    previous: number;
  };
  searchSignals: { keyword: string; traffic: string; publishedAt: string }[];
  publishedAt: string;
  articles: NewsArticle[];
  evidence: never[];
  reviewStatus: "unreviewed";
}
export interface RadarPage {
  schemaVersion: 1;
  date: string;
  runId: string;
  generatedAt: string;
  lastAttemptAt: string;
  status: "ok" | "partial" | "unavailable";
  selectionMethod: "rules-shortlist-human-review";
  baselineAvailable: boolean;
  items: RadarItem[];
  sources: {
    name: string;
    url: string;
    kind: "news" | "search";
    status: "ok" | "error";
    items: number;
    note?: string;
    error?: string;
  }[];
  shortfall: number;
  notice: string;
}
const HOSTS: Record<string, string[]> = {
  연합뉴스: ["www.yna.co.kr", "yna.co.kr"],
  동아일보: ["www.donga.com"],
  한겨레: ["www.hani.co.kr"],
  경향신문: ["www.khan.co.kr"],
};
export function radarSource(value: string, publisher: string): string | null {
  try {
    const url = new URL(value);
    return url.protocol === "https:" &&
      !url.username &&
      !url.password &&
      (!url.port || url.port === "443") &&
      HOSTS[publisher]?.includes(url.hostname) &&
      value.length <= 2048
      ? url.href
      : null;
  } catch {
    return null;
  }
}
const obj = (v: unknown): v is Record<string, unknown> =>
  Boolean(v) && typeof v === "object" && !Array.isArray(v);
const str = (v: unknown, max = 300): v is string =>
  typeof v === "string" && v.length > 0 && v.length <= max;
const count = (v: unknown) =>
  typeof v === "number" && Number.isInteger(v) && v >= 0 && v <= 2000;
const time = (v: unknown): v is string =>
  str(v, 40) &&
  /^\d{4}-\d\d-\d\dT.*(?:Z|[+-]\d\d:\d\d)$/.test(v) &&
  Number.isFinite(Date.parse(v));
function article(a: unknown): a is NewsArticle {
  return (
    obj(a) &&
    str(a.title) &&
    str(a.url, 2048) &&
    str(a.publisher, 30) &&
    Boolean(radarSource(a.url, a.publisher)) &&
    time(a.publishedAt)
  );
}
function item(v: unknown): v is RadarItem {
  return (
    obj(v) &&
    str(v.id, 32) &&
    /^news_[a-f0-9]{16}$/.test(v.id) &&
    str(v.title) &&
    str(v.question) &&
    str(v.reason, 1000) &&
    count(v.score) &&
    count(v.articleCount) &&
    count(v.publisherCount) &&
    count(v.independentSignals) &&
    time(v.publishedAt) &&
    v.reviewStatus === "unreviewed" &&
    Array.isArray(v.evidence) &&
    v.evidence.length === 0 &&
    Array.isArray(v.articles) &&
    v.articles.length > 0 &&
    v.articles.length <= 5 &&
    v.articles.every(article) &&
    obj(v.growth) &&
    ["no-baseline", "new", "rising", "steady"].includes(
      String(v.growth.status),
    ) &&
    count(v.growth.recent) &&
    count(v.growth.previous) &&
    Array.isArray(v.searchSignals) &&
    v.searchSignals.length <= 50 &&
    v.searchSignals.every(
      (t) =>
        obj(t) &&
        str(t.keyword) &&
        typeof t.traffic === "string" &&
        t.traffic.length <= 300 &&
        time(t.publishedAt),
    )
  );
}
export function isRadarPage(v: unknown): v is RadarPage {
  return (
    obj(v) &&
    v.schemaVersion === 1 &&
    str(v.date, 10) &&
    /^\d{4}-\d\d-\d\d$/.test(v.date) &&
    !Number.isNaN(Date.parse(v.date)) &&
    new Date(v.date).toISOString().slice(0, 10) === v.date &&
    str(v.runId, 80) &&
    time(v.generatedAt) &&
    time(v.lastAttemptAt) &&
    ["ok", "partial", "unavailable"].includes(String(v.status)) &&
    v.selectionMethod === "rules-shortlist-human-review" &&
    typeof v.baselineAvailable === "boolean" &&
    str(v.notice, 1000) &&
    count(v.shortfall) &&
    Array.isArray(v.items) &&
    v.items.length <= 10 &&
    v.items.every(item) &&
    new Set(v.items.map((i) => i.id)).size === v.items.length &&
    Array.isArray(v.sources) &&
    v.sources.length <= 8 &&
    v.sources.every(
      (s) =>
        obj(s) &&
        str(s.name, 50) &&
        str(s.url, 2048) &&
        ["news", "search"].includes(String(s.kind)) &&
        ["ok", "error"].includes(String(s.status)) &&
        count(s.items),
    )
  );
}
export function radarStale(at: string, now = Date.now()): boolean {
  return now - Date.parse(at) > 6 * 60 * 60 * 1000;
}
export function radarTime(at: string): string {
  return new Intl.DateTimeFormat("ko-KR", {
    timeZone: "Asia/Seoul",
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(at));
}
export const GROWTH = {
  "no-baseline": "비교 관측 쌓는 중",
  new: "새로 관측",
  rising: "보도 유입 증가",
  steady: "관측 중",
};
