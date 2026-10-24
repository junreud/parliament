import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { getIssue, getIssueTimeline, getIssueReading } from "@/lib/server-api";
import { REPRESENTATIVE_ISSUE_ID } from "@/lib/issue-reading";
import { PublicIssueReading } from "@/components/public-issue-reading";
import { TOPICS } from "@/lib/format";
import { FollowButton } from "@/components/interests";
import { ActivityList } from "@/components/activity-list";
import { ApiNotice } from "@/components/api-notice";
import { ContextTimeline, KnowledgeUnavailable } from "@/components/knowledge-panels";
import { EditorialIssueView } from "@/components/editorial-issue";
import { getEditorialIssue, canReadEditorial } from "@/lib/editorial-data";
import { isReviewedEditorial } from "@/lib/editorial";
import { GraphExploreLink } from "@/components/knowledge-graph";
export const dynamic = "force-dynamic";
type Props = { params: Promise<{ id: string }>; searchParams: Promise<{ cursor?: string }> };
export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const id = (await params).id;
  if (id === REPRESENTATIVE_ISSUE_ID) {
    const result = await getIssueReading(id);
    return result.status === "ok" ? { title: result.data.title, description: result.data.summary } : { title: "공개 이슈 해설", robots: { index: false } };
  }
  const editorial = getEditorialIssue(id);
  if (editorial) {
    if (!canReadEditorial(editorial)) notFound();
    return { title: editorial.title, description: editorial.summary, robots: { index: isReviewedEditorial(editorial), follow: true } };
  }
  const result = await getIssue(id);
  return result.status === "ok" ? { title: result.data.title, description: result.data.description } : { title: "이슈 기록", robots: { index: false } };
}
export default async function IssuePage({ params, searchParams }: Props) {
  const id = (await params).id;
  if (id === REPRESENTATIVE_ISSUE_ID) {
    const result = await getIssueReading(id);
    if (result.status === "not-found") notFound();
    return <PublicIssueReading id={id} result={result} />;
  }
  const editorial = getEditorialIssue(id);
  if (editorial) {
    if (!canReadEditorial(editorial)) notFound();
    return <EditorialIssueView issue={editorial} />;
  }
  const result = await getIssue(id);
  if (result.status === "not-found") notFound();
  if (result.status !== "ok") return <ApiNotice status={result.status} />;
  const issue = result.data;
  const timeline = await getIssueTimeline(issue.id, (await searchParams).cursor);
  return <><div className="breadcrumbs"><Link href="/issues">이슈</Link> / {TOPICS[issue.topic] || issue.topic}</div><header className="detail-header"><p className="eyebrow">Issue timeline</p><div className="detail-title-row"><h1>{issue.title}</h1><FollowButton kind="issue" targetId={issue.id} label={issue.title} /></div><p className="detail-summary">{issue.description}</p><p className="muted">아래는 연결이 확인된 공개 기록입니다. 비슷한 키워드만으로 별개의 행동을 같은 사건으로 합치지 않습니다.</p><GraphExploreLink kind="issue" id={issue.id} /></header><h2>연결된 변화</h2><KnowledgeUnavailable status={timeline.status} />{timeline.status === "ok" ? <><p className="muted">발생일을 확인한 기록은 발생일, 그 외 기록은 공개일로 정렬합니다. 날짜 종류를 각 기록에 표시합니다.</p>{timeline.data.items.length ? <ContextTimeline items={timeline.data.items} /> : <p className="notice">검수된 연결 기록이 아직 없습니다.</p>}{timeline.data.nextCursor && <div className="pagination"><Link className="button secondary" href={`/issues/${encodeURIComponent(issue.id)}?cursor=${encodeURIComponent(timeline.data.nextCursor)}`}>이전 기록 더 보기 →</Link></div>}</> : <ActivityList activities={issue.activities} />}</>;
}
