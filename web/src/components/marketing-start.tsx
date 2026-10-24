import { ReviewedIssueEntry } from "./reviewed-issue-entry";
import Link from "next/link";
import { MarketingVisit } from "./beta";
import { isReviewedEditorial, type EditorialIssue } from "@/lib/editorial";

export function MarketingStart({ issues }: { issues: EditorialIssue[] }) {
  const hasIssues = issues.length > 0;
  const pending = issues.some(issue => !isReviewedEditorial(issue));
  return <div className="marketing-start"><MarketingVisit />
    <header className="marketing-hero"><p className="marketing-kicker">나라의 근황 <span aria-hidden="true">→</span> 의정의 흐름</p><h1>흘려본 정치 뉴스,<br />맥락부터 근거까지.</h1><p>누군가는 이미 결론을 내렸지만,<br className="desktop-break" /> 나는 무슨 일인지부터 알고 싶을 때.</p><p className="marketing-intro">{hasIssues ? "인스타그램 ‘나라의 근황’에서 만난 질문을 ‘의정의 흐름’에서 이어 읽으세요. 사건의 배경과 현재 단계, 공식 원문과 다음 확인 지점을 한곳에 정리합니다." : "현재 첫 해설의 원문과 사건의 맥락을 검토하고 있습니다. 공개할 해설은 이곳에서 안내합니다."}</p><a href="#first-issues" className="button">{hasIssues ? "이슈부터 읽어보기 ↓" : "해설 준비 상태 보기 ↓"}</a><span className="marketing-free">{hasIssues ? "설치·로그인 없이 읽을 수 있습니다" : "공개 후 설치·로그인 없이 읽을 수 있습니다"}</span></header>
    <section className="marketing-promise" aria-label="읽는 순서"><div><span>01</span><h2>무슨 일이 있었는지</h2><p>처음 접해도 따라갈 수 있도록 배경과 흐름을 설명합니다.</p></div><div><span>02</span><h2>무엇이 확인됐는지</h2><p>공식 기록, 당사자의 주장, 아직 모르는 부분을 나눕니다.</p></div><div><span>03</span><h2>다음은 무엇인지</h2><p>발의·심사·의결·시행을 구분하고 다음 확인 지점을 남깁니다.</p></div></section>
    <ReviewedIssueEntry />
    <section id="first-issues" className="marketing-issues"><div className="section-heading"><h2>{hasIssues ? "지금, 함께 읽을 사건" : "첫 해설을 준비하고 있습니다"}</h2><span className="muted">{hasIssues ? "원문과 확인 범위까지" : "원문·맥락 검토 중"}</span></div>{pending && <p className="editorial-pending">지금은 해설을 준비하는 단계입니다. 아래 초안은 사람의 최종 검토를 기다리고 있으며, 검토가 끝나기 전에는 확정된 해설로 홍보하지 않습니다.</p>}{!hasIssues && <div className="empty-state"><p>검토가 끝난 이슈부터 순서대로 공개합니다. 현재 공개할 수 있는 해설은 아직 없습니다.</p><Link href="/about" className="text-link">편집과 정정 원칙 살펴보기 →</Link></div>}<div className="marketing-issue-grid">{issues.map((issue, index) => <Link href={`/issues/${encodeURIComponent(issue.id)}`} className="marketing-issue-card" key={issue.id}><span className="marketing-card-number">{String(index + 1).padStart(2, "0")} · {issue.topic}</span><h3>{issue.title}</h3><p>{issue.summary}</p><span className="editorial-status">{isReviewedEditorial(issue) ? "사람 검토 완료" : "사람 검토 전 · 해설 초안"}</span><span className="text-link">맥락과 근거 읽기 →</span></Link>)}</div></section>
    <section className="marketing-beta"><div><p className="eyebrow">함께 만드는 베타</p><h2>{hasIssues ? "읽고 나서 더 궁금해진 것이 있나요?" : "첫 해설을 함께 살펴볼 분을 찾습니다"}</h2><p>{hasIssues ? "어디서 이해가 막혔는지, 어떤 다음 변화가 궁금한지 알려주세요. 첫 읽기와 재방문 경험을 살펴볼 베타 연구 참여자를 찾습니다." : "해설이 공개되면 이해하기 쉬운지, 무엇이 더 궁금한지 살펴볼 예정입니다. 베타 연구의 목적과 참여 방법을 먼저 확인할 수 있습니다."}</p></div><Link href="/beta" className="button secondary">베타 연구 참여 안내</Link></section>
    <nav className="marketing-notes" aria-label="처음 방문한 분을 위한 안내"><Link href="/about">출처·정정 원칙 →</Link><Link href="/radar">뉴스에서 새로운 이슈 찾기 →</Link><a href="https://www.instagram.com/flow_goverment/" target="_blank" rel="noopener noreferrer">나라의 근황 인스타그램 ↗</a></nav>
  </div>;
}
