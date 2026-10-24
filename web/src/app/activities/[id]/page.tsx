import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { ApiNotice } from "@/components/api-notice";
import { ActivityFeedback } from "@/components/activity-feedback";
import { VoteTable } from "@/components/vote-table";
import { getActivity, getPerson, getActivityHistory, getActivityContext } from "@/lib/server-api";
import { ParticipantList, KnowledgeUnavailable, ScheduledTime } from "@/components/knowledge-panels";
import { EvidenceLinks } from "@/components/knowledge-evidence";
import { GraphExploreLink } from "@/components/knowledge-graph";
import { dateLabel, safeSource, STAGES, TOPICS, TYPES } from "@/lib/format";
export const dynamic = "force-dynamic";
type Props = { params: Promise<{ id: string }>; searchParams: Promise<{ version?: string }> };
export async function generateMetadata({ params, searchParams }: Props): Promise<Metadata> {
  const { id } = await params;
  const result = await getActivity(id, (await searchParams).version);
  return result.status === "ok" ? { title: result.data.title, description: result.data.summary?.slice(0, 150) } : { title: "기록 확인", robots: { index: false } };
}
export default async function ActivityPage({ params, searchParams }: Props) {
  const { id } = await params;
  const result = await getActivity(id, (await searchParams).version);
  if (result.status === "not-found") notFound();
  if (result.status !== "ok") return <ApiNotice status={result.status} />;
  const activity = result.data;
  const source = safeSource(activity.sourceUrl);
  const [history, context] = await Promise.all([getActivityHistory(activity.id), getActivityContext(activity.id, activity.version)]);
  const voteNames = new Map(activity.votes.map(vote => [vote.personId, vote.name]));
  const actors = await Promise.all(activity.personIds.slice(0, 12).map(async (personId, index) => {
    if (voteNames.has(personId)) return { id: personId, name: voteNames.get(personId)! };
    const person = await getPerson(personId);
    return { id: personId, name: person.status === "ok" ? person.data.name : `관련 인물 ${index + 1} · 이름 정보 미확인` };
  }));
  const feedbackEmail = process.env.FEEDBACK_EMAIL;
  const feedback = feedbackEmail && /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(feedbackEmail) ? `mailto:${feedbackEmail}?subject=${encodeURIComponent(`[기록 오류 제보] ${activity.id}`)}&body=${encodeURIComponent(`기록: ${activity.title}\n버전: ${activity.version}\n원문: ${activity.sourceUrl}\n\n오류가 있는 부분과 확인한 근거를 적어주세요:\n`)}` : null;
  return <><div className="breadcrumbs"><Link href="/">변화 피드</Link> / 기록 상세</div><header className="detail-header"><div className="card-meta"><span className="badge">{TYPES[activity.type] || activity.type}</span><span>{dateLabel(activity.occurredAt || activity.publishedAt)}</span>{activity.corrected && <span className="correction">정정된 기록</span>}</div><h1>{activity.title}</h1><p className="detail-summary">{activity.summary || "상세 설명은 아직 준비되지 않았습니다. 원문을 확인해 주세요."}</p><div className="tag-row"><span className="stage">{STAGES[activity.stage] || "단계 미확인"}</span>{activity.topics.map(topic => <Link className="topic" key={topic} href={`/?topic=${topic}`}>{TOPICS[topic] || topic}</Link>)}</div>{activity.type === "announcement" && <p className="notice">기관의 공식 발표 · 정책 효과는 별도 확인이 필요합니다.</p>}{activity.corrected && <p className="notice">정정 사항이 반영된 기록입니다. 아래 원문 버전과 공개 시점을 함께 확인해 주세요.</p>}<GraphExploreLink kind="activity" id={activity.id} /></header>
    <div className="detail-columns"><div><section className="detail-section" id="evidence"><h2>설명의 근거</h2><p className="muted">원문 발췌와 문서 위치를 확인하세요. 짧은 발췌만으로 앞뒤 문맥 전체를 대신하지 않습니다.</p>{activity.evidence.length ? activity.evidence.map(evidence => { const url = safeSource(evidence.sourceUrl); return <div className="evidence-block" key={evidence.id}><span className="badge">원문 발췌</span>{evidence.excerpt ? <blockquote>{evidence.excerpt}</blockquote> : <p className="muted">발췌 문장 없이 원천 필드를 근거로 연결한 기록입니다. 전체 원문에서 확인해 주세요.</p>}<span className="evidence-meta">위치: {evidence.locator || "문서 전체"} · 원문 버전: {evidence.sourceVersion}</span>{url && <a className="source-link" href={url} target="_blank" rel="noreferrer">전체 원문과 문맥 확인 ↗</a>}</div>; }) : <p className="notice">표시할 원문 구간이 아직 없습니다. 공식 원문을 직접 확인해 주세요.</p>}</section>
    <KnowledgeUnavailable status={context.status} />
    {context.status === "ok" && <ScheduledTime context={context.data} />}
    {context.status === "ok" && <section className="detail-section"><h2>연결된 문서와 문맥</h2><p className="muted">현재 보는 사건 버전에 고정된 근거입니다.</p><EvidenceLinks ids={context.data.evidence.map(evidence => evidence.id)} /><ul className="knowledge-list">{context.data.documents.map(document => <li key={`${document.id}:${document.version}`}><Link className="text-link" href={`/documents/${encodeURIComponent(document.id)}?${new URLSearchParams({ version: document.version, extractionVersion: document.extractionVersion })}`}>{document.title} →</Link></li>)}</ul></section>}
    {activity.billId && <section className="detail-section"><h2>연결된 법안</h2><Link className="text-link" href={`/bills/${encodeURIComponent(activity.billId)}`}>법안의 처리 과정과 표결 확인 →</Link></section>}
    {context.status === "ok" ? <section className="detail-section"><h2>확인된 인물 역할</h2><p className="muted">사건 당시 자격과 참여 근거를 확인하세요.</p><ParticipantList participants={context.data.participants} /></section> : activity.personIds.length > 0 && <section className="detail-section"><h2>관련 인물</h2><p className="muted">사건에 연결된 인물의 활동 기록으로 이동합니다.</p><div className="tag-row">{actors.map(actor => <Link className="button secondary" key={actor.id} href={`/people/${encodeURIComponent(actor.id)}`}>{actor.name}</Link>)}</div>{activity.personIds.length > actors.length && <p className="muted">관련 인물이 많아 첫 12명만 표시합니다. 전체 참여 기록은 아래 표결과 원문에서 확인하세요.</p>}</section>}
    {(activity.type === "vote" || activity.votes.length > 0) && <section className="detail-section"><h2>공개 표결</h2><p className="muted">개인별 기록이 없는 경우 찬반·기권·불참을 추정하지 않습니다.</p><VoteTable votes={activity.votes} /></section>}
    <section className="detail-section"><h2>설명과 정정 이력</h2>{history.status === "ok" && history.data.items.length ? <ol className="history-list">{history.data.items.map(entry => <li key={entry.version}><Link className="text-link" href={`/activities/${encodeURIComponent(activity.id)}?version=${encodeURIComponent(entry.version)}`}>{dateLabel(entry.reviewedAt)} · {entry.corrected ? "정정 공개" : "첫 공개"}{entry.version === activity.version ? " · 현재 보는 버전" : " · 이 버전 보기"}</Link>{entry.correctionReason && <p>{entry.correctionReason}</p>}</li>)}</ol> : <p className="muted">공개 이력을 불러오지 못했습니다. 현재 기록의 원문 버전은 위 근거에서 확인할 수 있습니다.</p>}</section>
    <ActivityFeedback key={`${activity.id}:${activity.version}`} activity={{ personIds: activity.personIds, topics: activity.topics, billId: activity.billId }} /></div><aside><section className="side-panel"><h2>자료 상태</h2><p>{activity.coverage || "공개 범위를 확인하고 있습니다."}</p><dl className="dates-list"><dt>발생일</dt><dd>{dateLabel(activity.occurredAt)}</dd><dt>원문 공개일</dt><dd>{dateLabel(activity.publishedAt)}</dd><dt>확인한 날짜</dt><dd>{dateLabel(activity.collectedAt)}</dd>{activity.changedAt && <><dt>변화 공개일</dt><dd>{dateLabel(activity.changedAt)}</dd></>}<dt>설명 버전</dt><dd>{activity.version}</dd></dl>{source && <p style={{ marginTop: 18 }}><a className="source-link" href={source} target="_blank" rel="noreferrer">공식 원문 확인 ↗</a></p>}<p><Link className="source-link" href={`/activities/${encodeURIComponent(activity.id)}?version=${encodeURIComponent(activity.version)}`}>이 버전의 기록 링크 →</Link></p><Link className="text-link" href="/coverage">전체 자료 범위 →</Link></section><section className="detail-section" style={{ marginTop: 20 }}><h2>오류를 발견했다면</h2><p className="muted">기록 ID·버전과 근거를 함께 알려주세요. 제보는 검토 후 정정 기록으로 반영합니다.</p>{feedback ? <a className="text-link" href={feedback}>메일 앱에서 제보 작성 ↗</a> : <p className="muted">제보 창구를 준비하고 있습니다. 우선 공식 원문을 함께 확인해 주세요.</p>}</section></aside></div>
  </>;
}
