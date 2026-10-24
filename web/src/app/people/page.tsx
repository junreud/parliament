import type { Metadata } from "next";
import Link from "next/link";
import { readApi } from "@/lib/api";
import type { Page, Person } from "@/lib/contracts";
import type { PeopleDirectory } from "@/lib/graph-contracts";
import { isEntityId } from "@/lib/knowledge-validation";
import { dateLabel } from "@/lib/format";
import { ApiNotice } from "@/components/api-notice";
export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "인물 기록", description: "의원과 정부인사의 공개 활동을 인물별로 확인합니다." };
export default async function PeoplePage({ searchParams }: { searchParams: Promise<{ query?: string; cursor?: string; organizationId?: string }> }) {
  const raw = await searchParams;
  const query = (raw.query || "").trim().slice(0, 100);
  const organizationId = isEntityId(raw.organizationId) ? raw.organizationId : "";
  const cursor = (raw.cursor || "").slice(0, 2000);
  const filters = { ...(query ? { query } : {}), ...(organizationId ? { organizationId } : {}) };
  const directory = await readApi<PeopleDirectory>(`/api/v1/knowledge/people?${new URLSearchParams({ limit: "40", ...filters, ...(cursor ? { cursor } : {}) })}`);
  const legacy = directory.status === "not-found" && !cursor && !organizationId
    ? await readApi<Page<Person>>(`/api/v1/people${query ? `?query=${encodeURIComponent(query)}` : ""}`) : null;
  const items = directory.status === "ok" ? directory.data.items : legacy?.status === "ok" ? legacy.data.items.map(person => ({
    id: person.id, name: person.name, kind: person.kind, position: person.role || null,
    organizationId: null, organizationName: person.organization || null, observedAt: null
  })) : [];
  const status = legacy?.status || directory.status;
  return <><p className="eyebrow">People</p><h1>사람의 활동을 따라가세요</h1><p className="muted">공개 자료에서 확인된 인물만 표시합니다. 명부 확보와 인물별 상세 활동 확보는 구분하며, 현재 직위와 사건 당시 직위의 근거를 함께 확인합니다.</p>
    <form className="search-form" action="/people"><label htmlFor="person-query">인물 이름 검색</label><input id="person-query" type="search" name="query" defaultValue={query} placeholder="인물 이름으로 검색" maxLength={100} />{organizationId && <input type="hidden" name="organizationId" value={organizationId} />}<button className="button">검색</button></form>
    {organizationId && <p className="muted">선택한 기관의 인물만 표시합니다. <Link className="text-link" href={`/people${query ? `?${new URLSearchParams({ query })}` : ""}`}>기관 필터 해제 →</Link></p>}
    {legacy?.status === "ok" && <p className="notice">기존 공개 명부를 표시합니다. 전국 명부의 추가 연결은 검수 후 제공됩니다.</p>}
    {status === "ok" && items.length ? <div className="browser-grid">{items.map(person => <Link className="browser-card" href={`/people/${encodeURIComponent(person.id)}`} key={person.id}><span className="badge">{person.kind === "LEGISLATOR" || person.kind === "legislator" ? "국회의원" : "공개 인물"}</span><h2>{person.name}</h2><p>{[person.organizationName, person.position].filter(Boolean).join(" · ") || "직위 정보 확인 중"}</p>{person.observedAt && <p className="evidence-meta">자료 확인일: {dateLabel(person.observedAt)}</p>}<span className="text-link">인물 문서와 활동 보기 →</span></Link>)}</div> : <ApiNotice status={status === "ok" ? "empty" : status} />}
    {directory.status === "ok" && directory.data.nextCursor && <div className="pagination"><Link className="button secondary" href={`/people?${new URLSearchParams({ ...filters, cursor: directory.data.nextCursor })}`}>다음 인물 더 보기 →</Link></div>}
    <p className="muted"><Link className="text-link" href="/coverage">출처별 수집 범위와 누락 상태 확인 →</Link></p>
  </>;
}
