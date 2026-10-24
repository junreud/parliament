import type { KnowledgeEvidence, PublicContext } from "./knowledge-contracts";
import type { Activity } from "./contracts";
import { isEntityId, isKnowledgePayload, isPublicContext } from "./knowledge-validation";
import { isInstant } from "./validation";

/** Selected public topic; its reading still requires a successful publication GET. */
export const REPRESENTATIVE_ISSUE_ID = "child-support-advance";

export interface IssueReadingBlock {
  id: string;
  kind: "background" | "fact" | "claim" | "unknown" | "event";
  text: string;
  date: string | null;
  title: string | null;
  evidenceIds: string[];
  personIds: string[];
}
export type IssueReadingContext = Omit<PublicContext, "activity"> & {
  activity: Omit<Activity, "changedAt"> & { changedAt?: string | null };
};
export interface IssueReading {
  schema: "issue-reading-v1";
  issueId: string;
  editorialId: string;
  editorialVersion: string;
  version: string;
  publicationState: "published";
  reviewedAt: string;
  publishedAt: string;
  checkedAt: string;
  title: string;
  summary: string;
  summaryEvidenceIds: string[];
  currentStage: string;
  stageEvidenceIds: string[];
  nextTrigger: string;
  coverage: string | null;
  blocks: IssueReadingBlock[];
  people: { id: string; name: string; evidenceIds: string[] }[];
  evidence: KnowledgeEvidence[];
  contexts: IssueReadingContext[];
  updates: { date: string; note: string }[];
}
export type IssueReadingResult =
  | { status: "ok"; data: IssueReading }
  | { status: "not-found" | "conflict" | "invalid" | "error" };

const object = (value: unknown): value is Record<string, unknown> =>
  value !== null && typeof value === "object" && !Array.isArray(value);
const text = (value: unknown, max = 8000): value is string =>
  typeof value === "string" && value.trim().length > 0 && value.length <= max;
const list = (value: unknown, max: number, min = 0): value is unknown[] =>
  Array.isArray(value) && value.length >= min && value.length <= max;
const ids = (value: unknown, min = 0): value is string[] =>
  list(value, 100, min) && value.every(isEntityId) && new Set(value).size === value.length;
const date = (value: unknown): value is string =>
  typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value) &&
  !Number.isNaN(Date.parse(value)) && new Date(value).toISOString().slice(0, 10) === value;
const instant = (value: unknown): value is string =>
  isInstant(value) && /(?:Z|[+-]\d{2}:\d{2})$/.test(value);
function publicMarkers(value: Record<string, unknown>): boolean {
  return ["visibility", "reviewState", "publicationStatus", "publicationState", "state"].every(
    key => !(key in value) || value[key] === "published",
  ) && (!("reviewStatus" in value) || value.reviewStatus === "reviewed") &&
    (!("decision" in value) || value.decision === "approved") &&
    !("rawStorageKey" in value);
}
function block(value: unknown): boolean {
  if (!object(value) || !publicMarkers(value) || !isEntityId(value.id) ||
      !text(value.text, 20000) || !ids(value.evidenceIds) || !ids(value.personIds) ||
      !["background", "fact", "claim", "unknown", "event"].includes(String(value.kind))) return false;
  return (value.kind === "unknown" || value.evidenceIds.length > 0) &&
    (value.kind === "event" ? date(value.date) && text(value.title, 2000) : value.date === null && value.title === null);
}
function evidence(value: unknown): boolean {
  if (!object(value) || !publicMarkers(value) || !isEntityId(value.id) ||
      !isKnowledgePayload(`/api/v1/evidence/${value.id}`, value)) return false;
  const e = value as unknown as KnowledgeEvidence;
  return text(e.documentVersion, 256) && text(e.extractionVersion, 256) &&
    text(e.excerpt, 20000) && e.before.length <= 4000 && e.after.length <= 4000 &&
    text(e.sourceUrl, 2048) && text(e.title, 2000) && e.mentions.length <= 1000 &&
    e.mentions.every(m => (m.decision === "approved" ? isEntityId(m.personId) : m.personId === null) &&
      !m.candidatePersonIds?.length &&
      (m.start < e.start || m.end > e.end || Array.from(e.excerpt).slice(m.start - e.start, m.end - e.start).join("") === m.surface));
}
function context(value: unknown): boolean {
  if (!object(value) || !object(value.activity)) return false;
  // The reading DTO explicitly uses null for an unknown optional change time.
  // Validate its equivalent omitted form without inventing a date or mutating the wire response.
  const compatible = value.activity.changedAt === null
    ? { ...value, activity: { ...value.activity, changedAt: undefined } } : value;
  return publicMarkers(value) && publicMarkers(value.activity) &&
    list(value.participants, 1000) && list(value.relations, 1000) && list(value.evidence, 100) &&
    list(value.documents, 100) && isPublicContext(compatible) &&
    instant(value.activity.publishedAt) && instant(value.activity.collectedAt) &&
    value.participants.every(p => object(p) && publicMarkers(p)) &&
    value.evidence.every(evidence) && value.relations.every(r => object(r) && publicMarkers(r)) &&
    value.documents.every(d => object(d) && publicMarkers(d));
}
function sameEvidence(left: KnowledgeEvidence, right: KnowledgeEvidence): boolean {
  return (["id", "documentId", "documentVersion", "extractionVersion", "segmentId", "start", "end", "excerpt"] as const)
    .every(key => left[key] === right[key]);
}
function linked(value: IssueReading): boolean {
  const ev = new Map(value.evidence.map(e => [e.id, e]));
  const people = new Map(value.people.map(p => [p.id, p]));
  const hasEvidence = (refs: string[]) => refs.every(id => ev.has(id));
  if (ev.size !== value.evidence.length || people.size !== value.people.length ||
      new Set(value.blocks.map(b => b.id)).size !== value.blocks.length ||
      new Set(value.contexts.map(c => `${c.eventId}:${c.eventVersion}`)).size !== value.contexts.length ||
      !hasEvidence(value.summaryEvidenceIds) || !hasEvidence(value.stageEvidenceIds)) return false;
  if (!value.evidence.every(e => value.contexts.some(c => c.evidence.some(other => sameEvidence(e, other))))) return false;
  if (!value.people.every(p => hasEvidence(p.evidenceIds) && value.contexts.some(c =>
    c.participants.some(actor => actor.personId === p.id && p.evidenceIds.every(id => actor.evidenceIds.includes(id)) &&
      c.relations.some(r => r.subjectId === p.id && r.type === actor.role && r.decision === "approved" &&
        (r.objectId === c.eventId || r.objectId === c.activity.billId) &&
        p.evidenceIds.every(id => r.evidenceIds.includes(id))))))) return false;
  return value.blocks.every(b => hasEvidence(b.evidenceIds) && b.personIds.every(id => {
    const person = people.get(id);
    return person && person.evidenceIds.some(e => b.evidenceIds.includes(e));
  }));
}
export function isIssueReading(issueId: string, value: unknown): value is IssueReading {
  if (!isEntityId(issueId) || !object(value) || !publicMarkers(value) ||
      value.schema !== "issue-reading-v1" || value.publicationState !== "published" || value.issueId !== issueId ||
      !isEntityId(value.editorialId) || typeof value.version !== "string" || !/^reading_[a-f0-9]{64}$/.test(value.version) ||
      typeof value.editorialVersion !== "string" || !/^[a-f0-9]{64}$/.test(value.editorialVersion) ||
      !instant(value.reviewedAt) || !instant(value.publishedAt) || Date.parse(value.reviewedAt) > Date.parse(value.publishedAt) ||
      !(date(value.checkedAt) || instant(value.checkedAt)) || !text(value.title, 2000) || !text(value.summary) ||
      !text(value.currentStage, 4000) || !text(value.nextTrigger, 4000) ||
      !(value.coverage === null || text(value.coverage)) ||
      !ids(value.summaryEvidenceIds, 1) || !ids(value.stageEvidenceIds, 1) ||
      !list(value.blocks, 200) || !value.blocks.every(block) ||
      !list(value.people, 10, 1) || !value.people.every(p => object(p) && publicMarkers(p) && isEntityId(p.id) && text(p.name, 500) && ids(p.evidenceIds, 1)) ||
      !list(value.evidence, 50, 1) || !value.evidence.every(evidence) ||
      !list(value.contexts, 20, 1) || !value.contexts.every(context) ||
      !list(value.updates, 200) || !value.updates.every(u => object(u) && date(u.date) && text(u.note))) return false;
  return linked(value as unknown as IssueReading);
}
export function issueReadingPath(id: string): string | null {
  return isEntityId(id) ? `/api/v1/issues/${id}/reading` : null;
}
export function issueReadingResponse(id: string, status: number, data?: unknown): IssueReadingResult {
  if (status === 400) return { status: "invalid" };
  if (status === 404) return { status: "not-found" };
  if (status === 409) return { status: "conflict" };
  return status === 200 && isIssueReading(id, data) ? { status: "ok", data } : { status: "error" };
}
