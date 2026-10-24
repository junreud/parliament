import type {
  KnowledgeGraph,
  GraphKind,
  GraphNode,
} from "../../../web/src/lib/graph-contracts";
import { GRAPH_KIND_LABELS } from "../../../web/src/lib/graph-contracts";
import type { Settings } from "../state";
import { useResource } from "./data";
import { OfficeDates, EvidenceLinks, PublicRefresh } from "./PublicMeta";
import { Icon } from "../components/Icon";

export function Connections({
  id,
  kind = "person",
  settings,
  onPerson,
  onActivity,
  onEvidence,
  onGraph,
}: {
  id: string;
  kind?: GraphKind;
  settings: Settings;
  onPerson: (id: string) => void;
  onActivity: (id: string) => void;
  onEvidence: (id: string) => void;
  onGraph: (kind: GraphKind, id: string) => void;
}) {
  const resource = useResource<KnowledgeGraph>(
    settings,
    `/api/v1/knowledge/graph?${new URLSearchParams({ rootKind: kind, rootId: id, depth: "2", limit: "40" })}`,
  );
  const graph = resource.data;
  const refresh = (
    <PublicRefresh
      settings={settings}
      loading={resource.status === "loading"}
      onRefresh={resource.reload}
      label="공개 연결 새로고침"
    />
  );
  const open = (node: GraphNode) => {
    if (node.kind === "person") onPerson(node.id);
    else if (node.kind === "activity") onActivity(node.id);
    else onGraph(node.kind, node.id);
  };
  if (resource.status === "loading")
    return (
      <>
        {refresh}
        <p role="status" className="loading-state">
          확인된 연결을 읽고 있어요.
        </p>
      </>
    );
  if (!graph)
    return (
      <>
        {refresh}
        <section className="person-empty">
          <p>
            {resource.status === "not-found"
              ? "공개된 연결 자료가 없어요"
              : "연결 자료를 불러오지 못했어요"}
          </p>
          <button className="text-button" onClick={resource.reload}>
            연결 재시도
          </button>
        </section>
      </>
    );
  const root = graph.nodes.find((node) => node.key === graph.rootKey)!;
  const others = graph.nodes.filter((node) => node.key !== graph.rootKey);
  return (
    <>
      {refresh}
      <p className="person-section-intro">
        원문에서 확인한 연결을 따라가요. 함께 등장했다는 이유만으로 협력이나
        공로를 뜻하지 않아요.
      </p>
      <div className="connection-list">
        {others.map((node) => {
          const direct = graph.edges.find(
            (edge) =>
              (edge.sourceKey === root.key && edge.targetKey === node.key) ||
              (edge.targetKey === root.key && edge.sourceKey === node.key),
          );
          const near = graph.edges.filter(
            (edge) =>
              edge.sourceKey === node.key || edge.targetKey === node.key,
          );
          const edge = direct || near[0];
          const middle = edge
            ? graph.nodes.find(
                (n) =>
                  n.key ===
                  (edge.sourceKey === node.key
                    ? edge.targetKey
                    : edge.sourceKey),
              )
            : null;
          return (
            <article className="connection-item" key={node.key}>
              <button
                className="person-card"
                aria-label={`${node.label} ${node.kind === "person" ? "인물 문서" : "연결 보기"}`}
                data-reader-focus={`connection-${node.key}`}
                onClick={() => open(node)}
              >
                <span className="person-avatar small">
                  <Icon
                    name={node.kind === "person" ? "family" : "shield"}
                    size={20}
                  />
                </span>
                <div>
                  <span className="eyebrow">
                    {GRAPH_KIND_LABELS[node.kind]}
                  </span>
                  <h3>{node.label}</h3>
                  <p>
                    {direct?.label ||
                      (middle
                        ? `${middle.label}에서 연결된 기록`
                        : "확인된 연결")}
                  </p>
                </div>
                <Icon name="arrow" size={18} />
              </button>
              {near.map((relation) => (
                <div className="connection-proof" key={relation.id}>
                  <p>{relation.label}</p>
                  {(relation.type === "holds_office" ||
                    relation.observedAt ||
                    relation.validFrom ||
                    relation.validUntil) && (
                    <OfficeDates
                      observedAt={relation.observedAt}
                      validFrom={relation.validFrom}
                      validUntil={relation.validUntil}
                    />
                  )}
                  <small>
                    공개 검수 시각 ·{" "}
                    {relation.reviewedAt
                      ? new Intl.DateTimeFormat("ko-KR", {
                          timeZone: "Asia/Seoul",
                          dateStyle: "short",
                          timeStyle: "short",
                        }).format(new Date(relation.reviewedAt))
                      : "미제공"}
                  </small>
                  <EvidenceLinks
                    ids={relation.evidenceIds}
                    onEvidence={onEvidence}
                    label="연결 근거"
                    focusKey={`connection-${node.key}-${relation.id}`}
                  />
                </div>
              ))}
            </article>
          );
        })}
      </div>
      {!others.length && (
        <p className="person-empty">현재 공개 범위에서 확인된 연결이 없어요.</p>
      )}
      {graph.truncated && (
        <p className="person-sample-note">
          일부 연결만 표시했어요. 다음 문서로 이동해 이어서 확인할 수 있어요.
        </p>
      )}
    </>
  );
}
