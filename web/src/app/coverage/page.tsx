import type { Metadata } from "next";
import { readApi } from "@/lib/api";
import type { Coverage, Page } from "@/lib/contracts";
import { dateLabel } from "@/lib/format";
import { ApiNotice } from "@/components/api-notice";
export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "자료 범위와 수집 상태" };
export default async function CoveragePage() {
  const result = await readApi<Page<Coverage>>("/api/v1/coverage");
  return <><p className="eyebrow">Source coverage</p><h1>어디까지 확인했는지 알려드립니다</h1><p className="muted">국회와 정부의 모든 행동이 공개되는 것은 아닙니다. 미공개, 미게시, 미수집, 수집 실패를 구분해 확인합니다.</p><p className="notice">제22대 국회 기록과 주요 정부 발표를 우선 확인합니다. 공식 발표·실제 의결·법령 시행·정책 효과는 서로 다른 단계입니다.</p>{result.status === "ok" && result.data.items.length ? <div className="activity-list">{result.data.items.map(item => <section className="detail-section" key={item.source}><div className="section-heading"><h2>{item.source}</h2><span className="badge">{["collected", "success_changed", "complete"].includes(item.status) ? "수집 확인" : item.status === "failed" ? "수집 실패" : item.status === "unverified" ? "검증 전" : ["no-new-records", "success_empty", "success_unchanged"].includes(item.status) ? "새 기록 없음" : ["running", "retrying"].includes(item.status) ? "확인 중" : item.status === "pending" ? "확인 대기" : item.status}</span></div><p>{item.note}</p><dl className="dates-list"><dt>확인한 범위</dt><dd>{item.range || "범위 확인 중"}</dd><dt>최근 확인일</dt><dd>{dateLabel(item.lastObservedAt)}</dd></dl></section>)}</div> : <ApiNotice status={result.status === "ok" ? "empty" : result.status} />}</>;
}
