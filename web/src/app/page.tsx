import Link from "next/link";
import type { Activity, Page } from "@/lib/contracts";
import { readApi } from "@/lib/api";
import { TOPICS, TYPES } from "@/lib/format";
import { ActivityFeed } from "@/components/feed";
import { FollowButton } from "@/components/interests";
import { editorialIssues } from "@/lib/editorial-data";
import { isReviewedEditorial } from "@/lib/editorial";
export const dynamic = "force-dynamic";
export default async function Home({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const params = await searchParams;
  const query = new URLSearchParams();
  for (const key of ["topic", "personId", "billId", "type", "cursor"]) if (typeof params[key] === "string" && params[key].trim()) query.set(key, params[key].trim());
  query.set("limit", "20");
  const result = await readApi<Page<Activity>>(`/api/v1/activities?${query}`);
  const next = result.status === "ok" ? result.data.nextCursor : null;
  if (next) query.set("cursor", next);
  return <>
    <section className="hero"><div><p className="eyebrow">Follow the public record</p><h1>관심 있는 정치,<br />그다음 변화를 놓치지 않도록.</h1><p>누가 무엇을 발표하고, 어떤 법안을 만들고, 어떻게 표결했는지.<br />짧게 읽고, 공식 기록에서 직접 확인하세요.</p></div><aside className="hero-note"><strong>쉽게 읽고, 깊게 확인</strong><span>발표에서 심사·의결·시행까지<br />서로 다른 단계를 구분해 보여줍니다.</span><Link href="/coverage">현재 확인한 자료 범위 →</Link></aside></section>
    {editorialIssues.filter(isReviewedEditorial).length >= 3 && <Link className="marketing-home-entry" href="/start"><strong>흘려본 뉴스의 맥락이 궁금하다면</strong><span>사건의 배경·현재 단계·원문을 함께 읽어보세요 →</span></Link>}
    <Link className="news-discovery-entry" href="/radar"><strong>지금, 무슨 이슈?</strong><span>뉴스에서 발견한 이슈와 원문 살펴보기 →</span></Link>
    <form className="filter-bar" action="/"><label htmlFor="topic-filter">주제</label><select name="topic" id="topic-filter" defaultValue={typeof params.topic === "string" ? params.topic : ""}><option value="">모든 주제</option>{Object.entries(TOPICS).map(([id, label]) => <option key={id} value={id}>{label}</option>)}</select><label htmlFor="type-filter">행동</label><select name="type" id="type-filter" defaultValue={typeof params.type === "string" ? params.type : ""}><option value="">모든 행동</option>{Object.entries(TYPES).map(([id, label]) => <option key={id} value={id}>{label}</option>)}</select><button className="button secondary">적용</button></form>
    <div className="feed-layout"><ActivityFeed initial={result} nextHref={next ? `/?${query}` : undefined} filtered={Boolean(params.topic || params.personId || params.billId || params.type)} /><aside className="side-panel"><p className="eyebrow">Your interests</p><h2>관심을 이어가세요</h2><p>처음에는 주제 하나부터.<br />인물과 법안도 함께 추적할 수 있습니다.</p><ul className="side-links">{Object.entries(TOPICS).map(([id, label]) => <li key={id}><Link href={`/?topic=${id}`}>{label}</Link><FollowButton kind="topic" targetId={id} label={label} /></li>)}</ul><p style={{ marginTop: 18 }}>기본 사실과 근거 열람은<br />로그인 없이 이용할 수 있습니다.</p><Link href="/interests" className="text-link">내 관심 설정 →</Link></aside></div>
  </>;
}
