import Link from "next/link";
import type { Activity } from "@/lib/contracts";
import { dateLabel, safeSource, STAGES, TOPICS, TYPES } from "@/lib/format";
export function ActivityCard({ activity, compact = false }: { activity: Activity; compact?: boolean }) {
  const source = safeSource(activity.sourceUrl);
  return <article className="activity-card">
    <div className="card-meta"><span className="badge">{TYPES[activity.type] || activity.type}</span><span>{activity.changedAt ? `변화 공개 ${dateLabel(activity.changedAt)}` : dateLabel(activity.occurredAt || activity.publishedAt)}</span>{activity.corrected && <span className="correction">정정된 기록</span>}</div>
    <h3><Link href={`/activities/${encodeURIComponent(activity.id)}`}>{activity.title}</Link></h3>
    <p className="card-summary">{activity.summary || "설명이 아직 준비되지 않았습니다. 원문에서 내용을 확인할 수 있습니다."}</p>
    <div className="tag-row"><span className="stage">{STAGES[activity.stage] || "단계 미확인"}</span>{activity.topics.map(topic => <Link key={topic} href={`/?topic=${encodeURIComponent(topic)}`} className="topic">{TOPICS[topic] || topic}</Link>)}</div>
    {!compact && activity.type === "announcement" && <p className="claim-note">기관의 공식 발표 · 정책 효과는 별도 확인이 필요합니다.</p>}
    {!compact && <p className="coverage-note">{activity.coverage || "공개된 기록의 범위를 확인하고 있습니다."}</p>}
    <div className="card-actions"><Link href={`/activities/${encodeURIComponent(activity.id)}`}>기록과 근거 읽기 <span aria-hidden="true">→</span></Link>{source && <a href={source} target="_blank" rel="noreferrer">원문 확인 ↗</a>}</div>
  </article>;
}
