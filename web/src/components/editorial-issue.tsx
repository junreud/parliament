import Link from "next/link";
import { BetaDepthLink, BetaExplainerOpened, BetaTimeline } from "./beta";
import { dateLabel, safeSource } from "@/lib/format";
import { isReviewedEditorial, type EditorialIssue } from "@/lib/editorial";

export function EditorialIssueView({ issue }: { issue: EditorialIssue }) {
  const reviewed = isReviewedEditorial(issue);
  return <article className="editorial-article"><BetaExplainerOpened key={issue.id} eligible={reviewed} />
    <div className="breadcrumbs"><Link href="/start">나라의 근황에서 온 분께</Link> / {issue.topic}</div>
    <header className="editorial-header"><p className="eyebrow">사건의 맥락 · 의정의 흐름</p><span className={`editorial-status ${reviewed ? "is-reviewed" : ""}`}>{reviewed ? "사람 검토 완료" : "사람 검토 전 · 해설 초안"}</span><h1>{issue.title}</h1><p className="detail-summary">{issue.summary}</p><p className="muted">마지막 원문 확인 {dateLabel(issue.checkedAt)}{reviewed ? ` · 검토 ${dateLabel(issue.reviewedAt)}` : " · 외부 홍보 전 사실·맥락·사용 조건을 검토할 예정입니다."}</p></header>
    {!reviewed && <p className="editorial-pending" role="note">이 페이지는 원문을 바탕으로 준비한 해설 초안입니다. 아직 사람의 최종 검토를 거치지 않았습니다. 확정된 해설로 공유하기 전에 원문과 확인 범위를 함께 살펴봐 주세요.</p>}
    <div className="editorial-layout"><div>
      <section className="detail-section"><h2>{issue.question}</h2>{issue.background.map((text, index) => <p key={index}>{text}</p>)}</section>
      <section className="detail-section"><h2>확인된 내용</h2><ul className="editorial-facts">{issue.facts.map((text, index) => <li key={index}>{text}</li>)}</ul></section>
      {issue.claims.length > 0 && <section className="detail-section"><h2>당사자의 입장·주장</h2><p className="muted">발표와 발언은 당사자의 입장입니다. 실제 이행이나 효과와 구분합니다.</p>{issue.claims.map((text, index) => <p key={index}>{text}</p>)}</section>}
      <section className="detail-section"><h2>아직 확인하지 못한 부분</h2>{issue.unknowns.map((text, index) => <p key={index}>{text}</p>)}</section>
      <section className="detail-section"><BetaTimeline key={issue.id} eligible={reviewed}><ol className="editorial-timeline-list">{issue.timeline.map((item, index) => <li key={index}><time>{dateLabel(item.date)}</time><h3>{item.title}</h3><p>{item.detail}</p><div className="knowledge-links">{item.sourceIds.map(sourceId => { const source = issue.sources.find(source => source.id === sourceId); return source ? <a href={`#source-${source.id}`} key={sourceId} className="text-link">{source.publisher} 근거 ↓</a> : null; })}</div></li>)}</ol></BetaTimeline></section>
      <section className="detail-section" aria-labelledby="editorial-sources"><h2 id="editorial-sources">설명에 사용한 원문</h2><p className="muted">문서에 표시된 날짜와 마지막 확인일을 구분합니다. 해설은 원문을 대신하지 않습니다.</p>{issue.sources.map(source => { const url = safeSource(source.url); return <div className="editorial-source" id={`source-${source.id}`} key={source.id}><p className="eyebrow">{source.sourceType === "official-position" ? "기관의 공식 입장" : "공식 기록"}</p><h3>{url ? <BetaDepthLink href={url} eligible={reviewed} target="_blank" rel="noopener noreferrer">{source.title} ↗</BetaDepthLink> : source.title}</h3><p>{source.publisher} · 문서 날짜 {dateLabel(source.publishedAt)}</p><p className="source-locator">{source.locator}</p><p className="muted">{source.usageNote}</p>{!url && <p className="muted">원문 주소의 안전성을 확인하지 못해 링크를 표시하지 않습니다.</p>}</div>; })}</section>
      <section className="editorial-updates"><h2>확인·변경 이력</h2><ul>{issue.updates.map((update, index) => <li key={index}><time>{dateLabel(update.date)}</time> {update.note}</li>)}</ul><Link href="/about" className="text-link">편집·정정 원칙 →</Link></section>
    </div><aside className="editorial-aside"><div className="detail-section"><p className="eyebrow">지금 어느 단계인가요?</p><h2>{issue.currentStage}</h2><p className="muted">다음에 확인할 지점</p><p>{issue.nextTrigger}</p><p className="muted">실제 변화가 확인되면 이 페이지의 근거와 이력을 갱신합니다.</p></div><div className="detail-section beta-invite"><h2>읽고 나서, 무엇이 남았나요?</h2><p>더 이해하기 쉬운 서비스를 만들고 있습니다. 사용 경험을 알려줄 베타 참여자를 찾습니다.</p><Link href="/beta" className="button secondary">베타 연구 알아보기</Link><p className="muted">참여 없이도 계속 읽을 수 있습니다.</p></div></aside></div>
    <div className="editorial-end"><Link href="/start" className="text-link">다른 사건의 맥락 읽기 →</Link><Link href="/radar" className="text-link">뉴스에서 새로운 이슈 찾기 →</Link></div>
  </article>;
}
