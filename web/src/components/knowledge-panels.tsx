"use client";
import { useState } from "react";
import Link from "next/link";
import type { Participant, PublicContext, KnowledgeRelation, PersonProfile } from "@/lib/knowledge-contracts";
import { dateLabel, STAGES, TYPES } from "@/lib/format";
import { EvidenceLinks } from "./knowledge-evidence";
import type { BillSummaryResult } from "@/lib/bill-lineage";

const ROLES: Record<string, string> = { lead_sponsor: "대표발의", co_sponsor: "공동발의", speaker: "발언", voter: "표결 참여", scheduled_participant: "참여 예정" };

export function ScheduledTime({ context }: { context: PublicContext }) {
  return context.scheduledAt ? <p className="notice">예정일: <time dateTime={context.scheduledAt}>{dateLabel(context.scheduledAt)}</time> · 실제 진행 여부는 후속 기록에서 확인하세요.</p> : null;
}

export function ParticipantList({ participants }: { participants: Participant[] }) {
  if (!participants.length) return <p className="muted">개인 참여 역할은 아직 확인되지 않았습니다.</p>;
  return <ul className="participant-list">{participants.map(participant => <li key={`${participant.personId}:${participant.role}`}>
    <div className="tag-row"><Link className="text-link" href={`/people/${encodeURIComponent(participant.personId)}`}>{participant.name}</Link><span className="badge">{ROLES[participant.role] || "역할 미확인"}</span></div>
    {[participant.organizationAtTime, participant.positionAtTime].some(Boolean) && <p className="muted">{[participant.organizationAtTime, participant.positionAtTime].filter(Boolean).join(" · ")}</p>}
    <EvidenceLinks ids={participant.evidenceIds} />
  </li>)}</ul>;
}

export function BillRelations({ billId, items, billSummaries = {} }: { billId: string; items: KnowledgeRelation[]; billSummaries?: Record<string, BillSummaryResult> }) {
  const lineage = items.filter(item => item.decision === "approved" && item.type === "incorporated_into_alternative" && (item.subjectId === billId || item.objectId === billId));
  return <section className="detail-section"><h2>원안과 대안의 연결</h2><p className="muted">각 법안은 별개 기록으로 보존합니다. 통합 관계는 특정 조항의 기여나 정책 전체의 공로를 뜻하지 않습니다.</p>
    {lineage.length ? <ul className="knowledge-list">{lineage.map(item => {
      const targetId = item.subjectId === billId ? item.objectId : item.subjectId;
      const summary = billSummaries[targetId];
      const bill = summary?.status === "ok" ? summary.data : null;
      return <li key={item.id}>
        <p><span className="badge">{item.subjectId === billId ? "대안에 통합됨" : "이 대안에 통합된 원안"}</span> <Link className="text-link" href={`/bills/${encodeURIComponent(targetId)}`}>{bill?.title || targetId}</Link></p>
        <p><span className="stage">{bill ? STAGES[bill.stage] || "단계 미확인" : "단계 미확인"}</span></p>
        {!bill && <p className="muted">식별자: {targetId} · {summary?.status === "offline" ? "법안 제목과 처리 상태를 불러오지 못했습니다." : summary?.status === "not-found" ? "연결된 법안의 제목과 처리 상태가 아직 공개되지 않았습니다." : "법안 제목과 처리 상태는 상세 기록에서 확인해 주세요."}</p>}
        <p className="muted">{item.reason}</p><EvidenceLinks ids={item.evidenceIds} />
      </li>;
    })}</ul> : <p className="muted">확인된 대안 연결이 없습니다.</p>}
  </section>;
}

export function ContextTimeline({ items }: { items: PublicContext[] }) {
  return <ol className="context-timeline">{items.map(context => {
    const activity = context.activity;
    const time = activity.occurredAt || activity.publishedAt;
    return <li className="activity-card" key={`${context.eventId}:${context.eventVersion}`}>
      <div className="card-meta"><span className="badge">{TYPES[activity.type] || activity.type}</span><time dateTime={time}>{dateLabel(time)} · {activity.occurredAt ? "발생일 기준" : "공개일 기준"}</time>{activity.corrected && <span className="correction">정정된 기록</span>}</div>
      <h3><Link href={`/activities/${encodeURIComponent(context.eventId)}?version=${encodeURIComponent(context.eventVersion)}`}>{activity.title}</Link></h3>
      {activity.summary && <p className="card-summary">{activity.summary}</p>}<p><span className="stage">{STAGES[activity.stage] || "단계 미확인"}</span></p>
      {activity.stage === "scheduled" && <p className="notice">예정된 활동을 알린 기록입니다. 실제 진행 결과는 후속 기록에서 확인하세요.</p>}
      <ScheduledTime context={context} />
      <ParticipantList participants={context.participants} />
      {context.evidence.length > 0 && <EvidenceLinks ids={context.evidence.map(evidence => evidence.id)} />}
    </li>;
  })}</ol>;
}

export function PersonActivities({ personId, contexts }: { personId: string; contexts: PublicContext[] }) {
  const [role, setRole] = useState("all");
  const items = contexts.filter(context => context.participants.some(participant => participant.personId === personId && (role === "all" || participant.role === role)));
  return <section aria-label="역할별 인물 활동"><div className="filter-bar"><label htmlFor="person-role">활동 역할</label><select id="person-role" value={role} onChange={event => setRole(event.target.value)}><option value="all">모든 확인된 역할</option>{Object.entries(ROLES).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></div>
    {items.length ? <ContextTimeline items={items} /> : <p className="notice">이 역할로 확인된 활동이 없습니다.</p>}
    <p className="muted">원문에 이름만 언급된 기록은 개인 활동에 포함하지 않습니다. 이 목록에는 최근 확인된 활동 최대 100건을 표시합니다.</p>
  </section>;
}

export function PersonProfileDetails({ profile }: { profile: PersonProfile }) {
  const rosterLabels: Record<string, string> = { source_current_roster: "원천의 현재 명부에서 확인", source_profile: "기관 소개에서 확인", source_rendered_profile: "기관 소개에서 확인", source_dated_office_statement: "발표 당시 직위 · 현재 재임 미확인", source_dated_acting_statement: "발표 당시 직무대행 · 현재 재임 미확인", source_dated_appointment: "임명 발표 확인 · 현재 재임 검수 대기", source_superseded_profile: "옛 직위 · 기관 소개 갱신 지연 확인", source_legal_ex_officio_candidate: "법정 겸직 연결 검수 대기", source_local_candidate: "출처별 신원 검토 대상", unresolved: "다른 출처와의 신원 연결 미확인", unknown: "미확인" };
  return <>
    <section className="detail-section"><h2>근거가 확인된 소개</h2>{profile.facts.length ? <dl className="profile-facts">{profile.facts.map((fact, index) => <div key={`${fact.label}:${index}`}><dt>{fact.label}</dt><dd>{["명부 현재성", "신원 연결 상태"].includes(fact.label) ? rosterLabels[fact.value] || "미확인" : fact.value}<EvidenceLinks ids={fact.evidenceIds} /></dd></div>)}</dl> : <p className="muted">소개 사실을 확인하고 있습니다.</p>}</section>
    <section className="detail-section"><h2>직위와 소속 이력</h2>{profile.tenures.length ? <ul className="knowledge-list">{profile.tenures.map((tenure, index) => <li key={`${tenure.organizationId}:${index}`}>
      <p><strong>{tenure.organizationName || tenure.organizationId} · {tenure.position}</strong>{tenure.party && ` · ${tenure.party}`}</p>
      <p className="muted">자료 관측일 · {dateLabel(tenure.observedAt)}</p>
      <p className="muted">효력 기간 · {tenure.validFrom ? dateLabel(tenure.validFrom) : "시작일 미확인"} ~ {tenure.validUntil ? dateLabel(tenure.validUntil) : "종료일 미확인"}</p><EvidenceLinks ids={tenure.evidenceIds} />
    </li>)}</ul> : <p className="muted">확인된 직위 이력이 없습니다.</p>}</section>
    {profile.relatedIssues.length > 0 && <section className="detail-section"><h2>관련 이슈</h2><ul className="knowledge-list">{profile.relatedIssues.map(issue => <li key={issue.id}><Link className="text-link" href={`/issues/${encodeURIComponent(issue.id)}`}>{issue.title} →</Link></li>)}</ul></section>}
  </>;
}

export function KnowledgeUnavailable({ status }: { status: string }) {
  return status === "offline" ? <p className="notice" role="status">연결된 인물·문서·근거를 불러오지 못했습니다. 연결 실패는 관련 기록이 없다는 뜻이 아닙니다.</p> : null;
}
