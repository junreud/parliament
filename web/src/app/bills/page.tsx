import type { Metadata } from "next";
import Link from "next/link";
import { readApi } from "@/lib/api";
import type { Bill, Page } from "@/lib/contracts";
import { STAGES } from "@/lib/format";
import { ApiNotice } from "@/components/api-notice";
export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "법안과 처리 과정" };
export default async function BillsPage({ searchParams }: { searchParams: Promise<{ query?: string }> }) {
  const { query = "" } = await searchParams;
  const result = await readApi<Page<Bill>>(`/api/v1/bills${query.trim() ? `?query=${encodeURIComponent(query.trim())}` : ""}`);
  return <><p className="eyebrow">Bills</p><h1>법안은 지금 어느 단계일까요?</h1><p className="muted">발의·심사·의결·공포·시행을 구분해서 읽으세요. 법안을 발의했다는 사실이 통과를 뜻하지 않습니다.</p><form className="search-form" action="/bills"><label htmlFor="bill-query">법안 검색</label><input id="bill-query" type="search" name="query" defaultValue={query} placeholder="법안 이름으로 검색" maxLength={100} /><button className="button">검색</button></form>{result.status === "ok" && result.data.items.length ? <div className="browser-grid">{result.data.items.map(bill => <Link className="browser-card" href={`/bills/${encodeURIComponent(bill.id)}`} key={bill.id}><span className="badge">{STAGES[bill.stage] || "단계 미확인"}</span><h2>{bill.title}</h2><p>법안 ID · {bill.id}</p><span className="text-link">처리 과정과 표결 보기 →</span></Link>)}</div> : <ApiNotice status={result.status === "ok" ? "empty" : result.status} />}</>;
}
