import type { Metadata } from "next";
import Link from "next/link";
import { readApi } from "@/lib/api";
import type { Activity, Page } from "@/lib/contracts";
import { ActivityList } from "@/components/activity-list";
import { ApiNotice } from "@/components/api-notice";
export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "공개 기록 검색", robots: { index: false } };
export default async function SearchPage({ searchParams }: { searchParams: Promise<{ q?: string; cursor?: string }> }) {
  const { q = "", cursor } = await searchParams;
  const query = new URLSearchParams({ q, limit: "20" });
  if (cursor) query.set("cursor", cursor);
  const result = q.trim() ? await readApi<Page<Activity>>(`/api/v1/search?${query}`) : null;
  if (result?.status === "ok" && result.data.nextCursor) query.set("cursor", result.data.nextCursor);
  return <><p className="eyebrow">Search public records</p><h1>궁금한 기록을 찾아보세요</h1><p className="muted">법안·발표·발언·표결의 제목과 설명에서 검색합니다.</p><form className="search-form" action="/search"><label htmlFor="search-query">공개 기록 검색어</label><input id="search-query" name="q" type="search" defaultValue={q} placeholder="예: 주거, 노동, 세금" required maxLength={100} /><button className="button">검색</button></form>{result === null ? <p className="notice">검색어를 입력하면 수집과 검증이 완료된 공개 기록을 확인할 수 있습니다.</p> : result.status === "ok" ? <><p className="result-count">“{q}” · 현재 페이지 {result.data.items.length}건</p><ActivityList activities={result.data.items} />{result.data.nextCursor && <div className="pagination"><Link href={`/search?${query}`} className="button secondary">다음 기록 보기</Link></div>}</> : <ApiNotice status={result.status} />}</>;
}
