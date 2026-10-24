import { GRAPH_KINDS, GRAPH_RELATIONS, type GraphKind, type KnowledgeGraph, type PeopleDirectory } from "./graph-contracts";
import { isEntityId } from "./knowledge-validation";
import { isInstant } from "./validation";

function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}
function fields(value: Record<string, unknown>, names: string[]): boolean {
  return Object.keys(value).every(name => names.includes(name)) && names.every(name => name in value);
}
function text(value: unknown): value is string { return typeof value === "string" && value.length <= 2000; }
function nullableText(value: unknown): boolean { return value === null || text(value); }
function date(value: unknown): boolean {
  if (value === null || isInstant(value)) return true;
  return typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value) && !Number.isNaN(Date.parse(value)) && new Date(value).toISOString().slice(0, 10) === value;
}
export function isGraphKind(value: unknown): value is GraphKind {
  return GRAPH_KINDS.includes(value as GraphKind);
}
function href(value: Record<string, unknown>): boolean {
  if (value.href === null) return true;
  if (!text(value.href) || !value.href.startsWith("/") || value.href.startsWith("//") || /[\\#]/.test(value.href)) return false;
  const url = new URL(value.href, "https://parliament.invalid");
  const id = String(value.id);
  if (["organization", "policy"].includes(String(value.kind))) {
    return url.pathname === "/explore" && url.searchParams.size === 2 && url.searchParams.get("rootKind") === value.kind && url.searchParams.get("rootId") === id;
  }
  const paths: Record<string, string> = { person: "people", bill: "bills", activity: "activities", document: "documents", issue: "issues" };
  if (url.pathname !== `/${paths[String(value.kind)]}/${encodeURIComponent(id)}`) return false;
  const keys = [...url.searchParams.keys()];
  const allowed = value.kind === "document" ? ["version", "extractionVersion"] : value.kind === "activity" ? ["version"] : [];
  if (keys.some(key => !allowed.includes(key)) || new Set(keys).size !== keys.length) return false;
  if (url.searchParams.has("version") && url.searchParams.get("version") !== value.version) return false;
  if (value.version !== null && ["activity", "document"].includes(String(value.kind)) && !url.searchParams.has("version")) return false;
  return keys.every(key => /^[A-Za-z0-9_.:-]{1,128}$/.test(url.searchParams.get(key) || ""));
}
function node(value: unknown): boolean {
  return record(value) && fields(value, ["key", "id", "kind", "label", "href", "version"]) &&
    isEntityId(value.id) && isGraphKind(value.kind) && value.key === `${value.kind}:${value.id}` &&
    text(value.label) && value.label.length > 0 && nullableText(value.version) && href(value);
}
function edge(value: unknown): boolean {
  return record(value) && fields(value, ["id", "sourceKey", "targetKey", "type", "label", "evidenceIds", "batchId", "reviewedAt", "validFrom", "validUntil", "observedAt"]) &&
    isEntityId(value.id) && text(value.sourceKey) && text(value.targetKey) && GRAPH_RELATIONS.includes(value.type as never) &&
    text(value.label) && isEntityId(value.batchId) && Array.isArray(value.evidenceIds) && value.evidenceIds.length > 0 && value.evidenceIds.length <= 1000 && value.evidenceIds.every(isEntityId) &&
    (value.reviewedAt === null || isInstant(value.reviewedAt)) && date(value.validFrom) && date(value.validUntil) &&
    (value.observedAt === null || isInstant(value.observedAt));
}
export function isPublicGraph(value: unknown): value is KnowledgeGraph {
  if (!record(value) || !fields(value, ["rootKey", "nodes", "edges", "truncated", "visibility"]) || value.visibility !== "published" || typeof value.truncated !== "boolean" ||
      !text(value.rootKey) || !Array.isArray(value.nodes) || value.nodes.length < 1 || value.nodes.length > 100 || !value.nodes.every(node) ||
      !Array.isArray(value.edges) || value.edges.length > 1000 || !value.edges.every(edge)) return false;
  const keys = new Set(value.nodes.map(item => item.key));
  return keys.size === value.nodes.length && keys.has(value.rootKey) && new Set(value.edges.map(item => item.id)).size === value.edges.length &&
    value.edges.every(item => keys.has(item.sourceKey) && keys.has(item.targetKey));
}
export function isPeopleDirectory(value: unknown): value is PeopleDirectory {
  return record(value) && fields(value, ["items", "nextCursor"]) && Array.isArray(value.items) && value.items.length <= 100 &&
    value.items.every(item => record(item) && fields(item, ["id", "name", "kind", "position", "organizationId", "organizationName", "observedAt"]) &&
      isEntityId(item.id) && text(item.name) && text(item.kind) && nullableText(item.position) &&
      (item.organizationId === null || isEntityId(item.organizationId)) && nullableText(item.organizationName) && (item.observedAt === null || isInstant(item.observedAt))) &&
    new Set(value.items.map(item => item.id)).size === value.items.length && (value.nextCursor === null || (text(value.nextCursor) && value.nextCursor.length > 0));
}
export function isGraphPayload(path: string, value: unknown): boolean | null {
  const pathname = path.split("?")[0];
  if (pathname === "/api/v1/knowledge/graph") {
    if (!isPublicGraph(value)) return false;
    const kind = new URLSearchParams(path.split("?")[1] || "").get("rootKind");
    return kind === null || value.nodes.find(node => node.key === value.rootKey)?.kind === kind;
  }
  if (pathname === "/api/v1/knowledge/people") return isPeopleDirectory(value);
  return null;
}
