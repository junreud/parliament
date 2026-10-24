export const GRAPH_KINDS = ["person", "organization", "bill", "policy", "activity", "document", "issue"] as const;
export type GraphKind = typeof GRAPH_KINDS[number];
export const GRAPH_RELATIONS = [
  "lead_sponsor", "co_sponsor", "speaker", "voter", "scheduled_participant", "publisher",
  "implementing_agency", "committee_proposer", "incorporated_into_alternative", "concerns",
  "records", "holds_office", "in_issue", "supported_by"
] as const;
export type GraphRelation = typeof GRAPH_RELATIONS[number];
export interface GraphNode {
  key: string; id: string; kind: GraphKind; label: string; href: string | null; version: string | null;
}
export interface GraphEdge {
  id: string; sourceKey: string; targetKey: string; type: GraphRelation; label: string;
  evidenceIds: string[]; batchId: string; reviewedAt: string | null;
  validFrom: string | null; validUntil: string | null; observedAt: string | null;
}
export interface KnowledgeGraph {
  rootKey: string; nodes: GraphNode[]; edges: GraphEdge[]; truncated: boolean;
  visibility: "published";
}
export interface DirectoryPerson {
  id: string; name: string; kind: string; position: string | null;
  organizationId: string | null; organizationName: string | null; observedAt: string | null;
}
export interface PeopleDirectory { items: DirectoryPerson[]; nextCursor: string | null; }

export const GRAPH_KIND_LABELS: Record<GraphKind, string> = {
  person: "인물", organization: "기관", bill: "법안", policy: "정책",
  activity: "사건", document: "문서", issue: "이슈"
};
export const GRAPH_RELATION_LABELS: Record<GraphRelation, string> = {
  lead_sponsor: "대표발의", co_sponsor: "공동발의", speaker: "발언", voter: "표결 참여",
  scheduled_participant: "참여 예정", publisher: "기관 발표", implementing_agency: "담당 기관",
  committee_proposer: "위원회 제안", incorporated_into_alternative: "대안에 통합",
  concerns: "관련 정책", records: "기록한 사건", holds_office: "직위",
  in_issue: "관련 이슈", supported_by: "원문 근거"
};
export function graphExploreHref(kind: GraphKind, id: string): string {
  return `/explore?${new URLSearchParams({ rootKind: kind, rootId: id })}`;
}
