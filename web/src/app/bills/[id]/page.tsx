import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { getBill, getBillLineage } from "@/lib/server-api";
import { STAGES, safeSource } from "@/lib/format";
import { FollowButton } from "@/components/interests";
import { ActivityList } from "@/components/activity-list";
import { ApiNotice } from "@/components/api-notice";
import { VoteTable } from "@/components/vote-table";
import { BillRelations, KnowledgeUnavailable } from "@/components/knowledge-panels";
import { loadRelatedBillSummaries } from "@/lib/bill-lineage";
import { GraphExploreLink } from "@/components/knowledge-graph";
export const dynamic = "force-dynamic";
type Props = { params: Promise<{ id: string }> };
export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const result = await getBill((await params).id);
  return result.status === "ok" ? { title: result.data.title, description: `${result.data.title}의 처리 과정과 공개 표결 기록.` } : { title: "법안 기록", robots: { index: false } };
}
export default async function BillPage({ params }: Props) {
  const result = await getBill((await params).id);
  if (result.status === "not-found") notFound();
  if (result.status !== "ok") return <ApiNotice status={result.status} />;
  const bill = result.data;
  const lineage = await getBillLineage(bill.id);
  const billSummaries = lineage.status === "ok" ? await loadRelatedBillSummaries(bill.id, lineage.data.items) : {};
  const source = safeSource(bill.sourceUrl);
  return <><div className="breadcrumbs"><Link href="/bills">법안</Link> / 처리 과정</div><header className="detail-header"><p className="eyebrow">Bill record</p><div className="detail-title-row"><h1>{bill.title}</h1><FollowButton kind="bill" targetId={bill.id} label={bill.title} /></div><div className="tag-row"><span className="stage">{STAGES[bill.stage] || "단계 미확인"}</span></div><p className="muted">본회의 의결과 법령 시행은 다릅니다. 대안에 반영된 법안은 독립적인 통과로 표시하지 않습니다.</p>{source && <a href={source} className="source-link" target="_blank" rel="noreferrer">법안 공식 원문 확인 ↗</a>}<GraphExploreLink kind="bill" id={bill.id} /></header><KnowledgeUnavailable status={lineage.status} />{lineage.status === "ok" && <BillRelations billId={bill.id} items={lineage.data.items} billSummaries={billSummaries} />}<div className="section-heading"><h2>처리 과정과 연결된 변화</h2><Link className="text-link" href={`/?billId=${encodeURIComponent(bill.id)}`}>전체 기록 피드 →</Link></div><ActivityList activities={bill.activities} /><section className="detail-section" style={{ marginTop: 24 }}><h2>공개 표결 기록</h2><VoteTable votes={bill.votes || []} /></section></>;
}
