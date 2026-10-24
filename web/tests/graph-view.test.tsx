import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { KnowledgeGraphView } from "@/components/knowledge-graph";
import type { KnowledgeGraph } from "@/lib/graph-contracts";

const graph: KnowledgeGraph = {
  rootKey: "person:person-1", visibility: "published", truncated: false,
  nodes: [
    { key: "person:person-1", id: "person-1", kind: "person", label: "검증 인물", href: "/people/person-1", version: null },
    { key: "organization:org-1", id: "org-1", kind: "organization", label: "검증 기관", href: null, version: null }
  ],
  edges: [{ id: "edge-1", sourceKey: "person:person-1", targetKey: "organization:org-1", type: "holds_office", label: "의원", evidenceIds: ["evidence-1"], batchId: "batch-1", reviewedAt: "2026-10-09T00:00:00Z", validFrom: "2024-05-30", validUntil: null, observedAt: "2026-10-09T00:00:00Z" }]
};

describe("accessible evidence graph", () => {
  it("provides named links, typed relations and evidence through a keyboard readable list", () => {
    render(<KnowledgeGraphView graph={graph} />);
    expect(screen.getByRole("img", { name: /검증 인물.*관계/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "검증 인물 문서 보기" })).toHaveAttribute("href", "/people/person-1");
    expect(screen.getByRole("link", { name: "검증 기관에서 이어 보기" })).toHaveAttribute("href", "/explore?rootKind=organization&rootId=org-1");
    expect(screen.getByRole("link", { name: "근거 1 →" })).toHaveAttribute("href", "/evidence/evidence-1");
    expect(screen.getByText(/직위.*의원/)).toBeInTheDocument();
    expect(screen.getByText(/확인일/)).toBeInTheDocument();
  });

  it("labels a bounded graph without implying that other relationships do not exist", () => {
    render(<KnowledgeGraphView graph={{ ...graph, truncated: true }} />);
    expect(screen.getByRole("status")).toHaveTextContent("일부 연결만 표시");
  });

  it("distinguishes an unconnected reviewed root from source failure", () => {
    render(<KnowledgeGraphView graph={{ ...graph, nodes: [graph.nodes[0]], edges: [] }} />);
    expect(screen.getByText("이 인물·기록에서 검수된 연결이 아직 없습니다.")).toBeInTheDocument();
    expect(screen.queryByText(/기록 서버에 연결할 수 없습니다/)).not.toBeInTheDocument();
  });
});
