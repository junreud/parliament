import type { Metadata } from "next";
import Link from "next/link";
import { ApiNotice } from "@/components/api-notice";
import { KnowledgeGraphView } from "@/components/knowledge-graph";
import { readApi } from "@/lib/api";
import { GRAPH_KIND_LABELS, GRAPH_RELATIONS, GRAPH_RELATION_LABELS, type KnowledgeGraph } from "@/lib/graph-contracts";
import { isGraphKind } from "@/lib/graph-validation";
import { isEntityId } from "@/lib/knowledge-validation";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "근거와 관계 탐색", description: "인물·기관·법안·정책의 확인된 연결을 원문 근거와 함께 탐색합니다." };
type Query = { rootKind?: string; rootId?: string; depth?: string; relationType?: string };
export default async function ExplorePage({ searchParams }: { searchParams: Promise<Query> }) {
  const query = await searchParams;
  const kind = isGraphKind(query.rootKind) ? query.rootKind : "person";
  const depth = query.depth === "2" ? "2" : "1";
  const relationType = GRAPH_RELATIONS.includes(query.relationType as never) ? query.relationType : "";
  const id = query.rootId || "";
  const validKind = query.rootKind === undefined || isGraphKind(query.rootKind);
  const result = isEntityId(id) && validKind ? await readApi<KnowledgeGraph>(`/api/v1/knowledge/graph?${new URLSearchParams({ rootKind: kind, rootId: id, depth, limit: "40", ...(relationType ? { relationType } : {}) })}`) : null;
  return <><div className="breadcrumbs"><Link href="/people">인물 기록</Link> / 관계 탐색</div><p className="eyebrow">Evidence graph</p><h1>기록이 이어지는 길을 확인하세요</h1><p className="muted">공개 승인을 받은 연결만 표시합니다. 인물의 이름 언급과 실제 행동은 구분합니다.</p>
    {id && validKind && <form action="/explore" className="filter-bar graph-filter"><input type="hidden" name="rootId" value={id} /><input type="hidden" name="rootKind" value={kind} /><span className="badge">{GRAPH_KIND_LABELS[kind]}에서 탐색</span><label htmlFor="graph-depth">연결 깊이</label><select id="graph-depth" name="depth" defaultValue={depth}><option value="1">직접 연결</option><option value="2">두 단계 연결</option></select><label htmlFor="graph-relation">연결 종류</label><select id="graph-relation" name="relationType" defaultValue={relationType}><option value="">전체 연결</option>{GRAPH_RELATIONS.map(item => <option key={item} value={item}>{GRAPH_RELATION_LABELS[item]}</option>)}</select><button className="button">적용</button></form>}
    {result?.status === "ok" ? <KnowledgeGraphView graph={result.data} /> : result ? <ApiNotice status={result.status} /> : <div className="notice"><p>{id ? "유효한 인물·기록의 주소를 선택해 주세요." : "인물·법안·이슈 문서에서 관계 탐색을 선택하면 연결과 근거를 볼 수 있습니다."}</p><Link className="text-link" href="/people">인물 명부에서 시작하기 →</Link></div>}
  </>;
}
