import { describe, expect, it, vi } from "vitest";
import { isAllowedProxyPath, readApi } from "@/lib/api";
import { forwardApi } from "@/lib/proxy";
import { isPublicGraph, isPeopleDirectory } from "@/lib/graph-validation";
import type { KnowledgeGraph } from "@/lib/graph-contracts";

export const graph: KnowledgeGraph = {
  rootKey: "person:person-1", visibility: "published", truncated: false,
  nodes: [
    { key: "person:person-1", id: "person-1", kind: "person", label: "검증 인물", href: "/people/person-1", version: null },
    { key: "organization:org-1", id: "org-1", kind: "organization", label: "검증 기관", href: null, version: null }
  ],
  edges: [{ id: "edge-1", sourceKey: "person:person-1", targetKey: "organization:org-1", type: "holds_office", label: "의원", evidenceIds: ["evidence-1"], batchId: "batch-1", reviewedAt: "2026-10-09T00:00:00Z", validFrom: "2024-05-30", validUntil: null, observedAt: "2026-10-09T00:00:00Z" }]
};

describe("public graph and directory boundary", () => {
  it("allows only the two public GET resources and never forwards a candidate preview", async () => {
    expect(isAllowedProxyPath(["v1", "knowledge", "graph"], "GET")).toBe(true);
    expect(isAllowedProxyPath(["v1", "knowledge", "people"], "GET")).toBe(true);
    for (const path of [["v1", "knowledge", "review"], ["v1", "knowledge", "batches", "batch-1", "graph"], ["admin", "tracking", "knowledge", "batches", "batch-1", "graph"]]) {
      const fetcher = vi.fn();
      expect((await forwardApi(new Request("http://localhost:3000/api/" + path.join("/")), path, fetcher)).status).toBe(404);
      expect(fetcher).not.toHaveBeenCalled();
    }
    expect(isAllowedProxyPath(["v1", "knowledge", "graph"], "POST")).toBe(false);
    const path = "/api/v1/knowledge/graph?rootKind=person&rootId=person-1";
    expect((await readApi(path, async () => Response.json(graph))).status).toBe("ok");
    expect((await readApi(path, async () => Response.json({ ...graph, visibility: "candidate" }))).status).toBe("offline");
  });

  it("rejects dangling, duplicate, unsupported and ungrounded graph edges", () => {
    expect(isPublicGraph(graph)).toBe(true);
    expect(isPublicGraph({ ...graph, rootKey: "person:missing" })).toBe(false);
    expect(isPublicGraph({ ...graph, nodes: [...graph.nodes, graph.nodes[0]] })).toBe(false);
    expect(isPublicGraph({ ...graph, edges: [graph.edges[0], graph.edges[0]] })).toBe(false);
    for (const edge of [
      { ...graph.edges[0], targetKey: "person:missing" },
      { ...graph.edges[0], evidenceIds: [] },
      { ...graph.edges[0], type: "name_mentioned" }
    ]) expect(isPublicGraph({ ...graph, edges: [edge] })).toBe(false);
  });

  it("refuses external links, mismatched internal identities and private payload fields", () => {
    for (const node of [
      { ...graph.nodes[0], href: "https://attacker.example/" },
      { ...graph.nodes[0], href: "//attacker.example/" },
      { ...graph.nodes[0], href: "/people/person-2" },
      { ...graph.nodes[0], href: "/people/person-1?token=secret" },
      { ...graph.nodes[0], key: "bill:person-1" },
      { ...graph.nodes[0], rawStorageKey: ".local/private" }
    ]) expect(isPublicGraph({ ...graph, nodes: [node, graph.nodes[1]] })).toBe(false);
    expect(isPublicGraph({ ...graph, nodes: Array.from({ length: 101 }, (_, index) => ({ ...graph.nodes[0], id: `person-${index}`, key: `person:person-${index}`, href: `/people/person-${index}` })) })).toBe(false);
  });

  it("accepts a cursor directory with observed dates and rejects malformed identities", async () => {
    const directory = { items: [{ id: "person-1", name: "검증 인물", kind: "person", position: "의원", organizationId: "org-1", organizationName: "검증 기관", observedAt: "2026-10-09T00:00:00Z" }], nextCursor: "cursor-1" };
    expect(isPeopleDirectory(directory)).toBe(true);
    expect((await readApi("/api/v1/knowledge/people?limit=40", async () => Response.json(directory))).status).toBe("ok");
    expect(isPeopleDirectory({ ...directory, items: [{ ...directory.items[0], organizationId: "invalid:id" }] })).toBe(false);
    expect(isPeopleDirectory({ ...directory, nextCursor: 7 })).toBe(false);
  });
});
