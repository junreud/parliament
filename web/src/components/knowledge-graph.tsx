import Link from "next/link";
import { EvidenceLinks } from "./knowledge-evidence";
import { dateLabel } from "@/lib/format";
import { GRAPH_KIND_LABELS, GRAPH_RELATION_LABELS, graphExploreHref, type GraphNode, type KnowledgeGraph } from "@/lib/graph-contracts";

function positions(graph: KnowledgeGraph): { points: Map<string, { x: number; y: number }>; height: number } {
  const distances = new Map([[graph.rootKey, 0]]);
  for (let distance = 0; distance < 2; distance += 1) {
    for (const edge of graph.edges) {
      if (distances.get(edge.sourceKey) === distance && !distances.has(edge.targetKey)) distances.set(edge.targetKey, distance + 1);
      if (distances.get(edge.targetKey) === distance && !distances.has(edge.sourceKey)) distances.set(edge.sourceKey, distance + 1);
    }
  }
  const columns = [0, 1, 2].map(distance => graph.nodes.filter(node => (distances.get(node.key) ?? 2) === distance));
  const height = Math.max(350, ...columns.map(column => column.length * 110 + 70));
  const points = new Map<string, { x: number; y: number }>();
  columns.forEach((column, index) => column.forEach((node, row) => points.set(node.key, { x: 130 + index * 290, y: (row + 1) * height / (column.length + 1) })));
  return { points, height };
}
function nodeText(node: GraphNode): string {
  const points = Array.from(node.label);
  return points.length > 12 ? points.slice(0, 11).join("") + "…" : node.label;
}
export function GraphExploreLink({ kind, id }: { kind: GraphNode["kind"]; id: string }) {
  return <Link className="text-link" href={graphExploreHref(kind, id)}>인물·기관·기록의 관계 탐색 →</Link>;
}
export function KnowledgeGraphView({ graph }: { graph: KnowledgeGraph }) {
  const root = graph.nodes.find(node => node.key === graph.rootKey)!;
  const nodes = new Map(graph.nodes.map(node => [node.key, node]));
  const { points, height } = positions(graph);
  return <section className="knowledge-graph" aria-label="검수된 관계 그래프">
    <p className="muted">화살표는 근거로 확인한 역할과 연결을 나타냅니다. 연결이 있다는 이유로 정책의 공로나 효과를 추정하지 않습니다.</p>
    {graph.truncated && <p className="notice" role="status">일부 연결만 표시합니다. 인물·기관·기록을 선택하면 그 지점에서 이어 볼 수 있습니다.</p>}
    <div className="section-heading"><p className="result-count">인물·기록 {graph.nodes.length}개 · 연결 {graph.edges.length}개</p><a className="text-link" href="#graph-relations">연결 목록으로 이동 ↓</a></div>
    <div className="graph-canvas">
      <svg width="840" height={height} viewBox={`0 0 840 ${height}`} role="img" aria-label={`${root.label}의 검수된 관계 지도`}>
        <defs><marker id="graph-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" /></marker></defs>
        {graph.edges.map((edge, index) => {
          const source = points.get(edge.sourceKey)!;
          const target = points.get(edge.targetKey)!;
          const shift = source.x < target.x ? 48 : -48;
          return <g key={edge.id}><path className="graph-edge" d={`M ${source.x + shift} ${source.y} L ${target.x - shift} ${target.y}`} markerEnd="url(#graph-arrow)" /><title>{nodes.get(edge.sourceKey)?.label} → {edge.label} → {nodes.get(edge.targetKey)?.label}</title>{index < 40 && source.x !== target.x && <text className="graph-edge-label" x={(source.x + target.x) / 2} y={(source.y + target.y) / 2 - 8} textAnchor="middle">{edge.label}</text>}</g>;
        })}
        {graph.nodes.map(node => {
          const point = points.get(node.key)!;
          return <a key={node.key} href={graphExploreHref(node.kind, node.id)} aria-label={`${node.label} 연결 탐색`}>
            <g className={`graph-node${node.key === graph.rootKey ? " graph-root" : ""}`} transform={`translate(${point.x},${point.y})`}>
              <title>{node.label} · {GRAPH_KIND_LABELS[node.kind]}</title><circle r="43" /><text textAnchor="middle" y="-2">{GRAPH_KIND_LABELS[node.kind]}</text><text className="graph-node-name" textAnchor="middle" y="63">{nodeText(node)}</text>
            </g>
          </a>;
        })}
      </svg>
    </div>
    <p className="muted">지도는 가로·세로로 이동할 수 있습니다. 아래 목록에서 같은 연결과 근거를 확인할 수 있습니다.</p>
    <div className="graph-lists"><section aria-labelledby="graph-nodes-title"><h2 id="graph-nodes-title">인물과 기록</h2><ul className="knowledge-list">
      {graph.nodes.map(node => <li key={node.key}><span className="badge">{GRAPH_KIND_LABELS[node.kind]}</span><h3>{node.label}{node.key === graph.rootKey && <span className="graph-current"> · 탐색 기준</span>}</h3><div className="knowledge-links">{node.href && <Link className="text-link" href={node.href}>{node.label} 문서 보기</Link>}<Link className="text-link" href={graphExploreHref(node.kind, node.id)}>{node.label}에서 이어 보기</Link></div>{node.version && <p className="evidence-meta">기록 버전: {node.version}</p>}</li>)}
    </ul></section><section id="graph-relations" aria-labelledby="graph-relations-title"><h2 id="graph-relations-title">연결과 근거</h2>
      {graph.edges.length ? <ol className="graph-relations">{graph.edges.map(edge => <li key={edge.id}><p><strong>{nodes.get(edge.sourceKey)?.label}</strong> → <span>{GRAPH_RELATION_LABELS[edge.type]}{edge.label !== GRAPH_RELATION_LABELS[edge.type] ? ` · ${edge.label}` : ""}</span> → <strong>{nodes.get(edge.targetKey)?.label}</strong></p>{(edge.validFrom || edge.validUntil) && <p className="muted">확인된 기간: {edge.validFrom || "시작 미확인"} ~ {edge.validUntil || "종료 미확인"}</p>}{edge.observedAt && <p className="muted">확인일: {dateLabel(edge.observedAt)}</p>}<EvidenceLinks ids={edge.evidenceIds} /></li>)}</ol> : <p className="notice">이 인물·기록에서 검수된 연결이 아직 없습니다.</p>}
    </section></div>
  </section>;
}
