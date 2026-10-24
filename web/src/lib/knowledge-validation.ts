import { isActivity, isInstant } from "./validation";

function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}
export function isEntityId(value: unknown): value is string {
  return typeof value === "string" && /^[A-Za-z0-9_-]{1,128}$/.test(value);
}
function string(value: unknown): value is string { return typeof value === "string"; }
function nullableString(value: unknown): boolean { return value === null || string(value); }
function ids(value: unknown): boolean { return Array.isArray(value) && value.every(isEntityId); }
function knownDate(value: unknown): boolean {
  return value === null || isInstant(value) || (string(value) && /^\d{4}-\d{2}-\d{2}$/.test(value) && !Number.isNaN(Date.parse(value)));
}
function range(value: Record<string, unknown>): boolean {
  return Number.isSafeInteger(value.start) && Number.isSafeInteger(value.end) && Number(value.start) >= 0 && Number(value.end) > Number(value.start);
}
function mention(value: unknown): boolean {
  return record(value) && isEntityId(value.id) && string(value.surface) && range(value) &&
    ["pending", "approved", "rejected"].includes(String(value.decision)) &&
    (value.personId === null || isEntityId(value.personId)) &&
    (value.candidatePersonIds === undefined || ids(value.candidatePersonIds));
}
function segment(value: unknown): boolean {
  if (!record(value) || !isEntityId(value.id) || !string(value.text) || !string(value.locator) || !Array.isArray(value.mentions)) return false;
  const points = Array.from(value.text);
  return value.mentions.every(item => mention(item) && record(item) && Number(item.end) <= points.length && points.slice(Number(item.start), Number(item.end)).join("") === item.surface);
}
function document(value: unknown): boolean {
  return record(value) && isEntityId(value.id) &&
    ["version", "sourceKey", "recordKey", "sourceUrl", "title", "extractionVersion"].every(key => string(value[key])) &&
    ["html", "pdf", "json", "hwp", "hwpx"].includes(String(value.format)) &&
    ["available", "partial", "unavailable", "disclaimer_only", "unsupported", "failed"].includes(String(value.bodyStatus)) &&
    ["allowed", "restricted", "unknown"].includes(String(value.licenseStatus)) &&
    knownDate(value.publishedAt) && isInstant(value.collectedAt) &&
    (value.datePrecision === undefined || ["date", "second", "unknown"].includes(String(value.datePrecision))) &&
    Array.isArray(value.segments) && value.segments.every(segment) &&
    ((value.licenseStatus === "allowed") || value.segments.length === 0) && value.rawStorageKey === undefined;
}
function evidence(value: unknown): boolean {
  return record(value) && ["id", "documentId", "segmentId"].every(key => isEntityId(value[key])) &&
    ["documentVersion", "extractionVersion", "excerpt", "before", "after", "sourceUrl", "title"].every(key => string(value[key])) &&
    range(value) && Array.from(String(value.excerpt)).length === Number(value.end) - Number(value.start) &&
    (value.locator === undefined || string(value.locator)) && Array.isArray(value.mentions) && value.mentions.every(mention);
}
function relation(value: unknown): boolean {
  return record(value) && ["id", "subjectId", "objectId"].every(key => isEntityId(value[key])) &&
    ["lead_sponsor", "co_sponsor", "speaker", "voter", "scheduled_participant", "publisher", "implementing_agency", "committee_proposer", "incorporated_into_alternative", "concerns", "records"].includes(String(value.type)) &&
    ids(value.evidenceIds) && (value.evidenceIds as unknown[]).length > 0 && value.decision === "approved" && string(value.reason);
}
function participant(value: unknown): boolean {
  return record(value) && isEntityId(value.personId) && string(value.name) &&
    ["lead_sponsor", "co_sponsor", "speaker", "voter", "scheduled_participant"].includes(String(value.role)) &&
    ids(value.evidenceIds) && (value.evidenceIds as unknown[]).length > 0 && nullableString(value.organizationAtTime) && nullableString(value.positionAtTime);
}
export function isPublicContext(value: unknown): boolean {
  return record(value) && isEntityId(value.eventId) && string(value.eventVersion) &&
    ["new_record", "state_changed", "important_correction", "explanation_only", "extraction_only"].includes(String(value.changeKind)) &&
    isActivity(value.activity) && value.activity.id === value.eventId && value.activity.version === value.eventVersion &&
    (value.scheduledAt === undefined || value.scheduledAt === null || isInstant(value.scheduledAt)) &&
    (value.scheduledPrecision === undefined || value.scheduledPrecision === null || ["date", "second", "unknown"].includes(String(value.scheduledPrecision))) &&
    Array.isArray(value.participants) && value.participants.every(participant) &&
    Array.isArray(value.relations) && value.relations.every(relation) &&
    Array.isArray(value.evidence) && value.evidence.every(evidence) && Array.isArray(value.documents) && value.documents.every(document);
}
function profile(value: unknown): boolean {
  return record(value) && isEntityId(value.id) && string(value.name) && string(value.kind) &&
    Array.isArray(value.facts) && value.facts.every(item => record(item) && string(item.label) && string(item.value) && ids(item.evidenceIds) && (item.evidenceIds as unknown[]).length > 0) &&
    Array.isArray(value.tenures) && value.tenures.every(item => record(item) && isEntityId(item.organizationId) && (item.organizationName === undefined || string(item.organizationName)) && string(item.position) && nullableString(item.party) && knownDate(item.validFrom) && knownDate(item.validUntil) && isInstant(item.observedAt) && ids(item.evidenceIds) && (item.evidenceIds as unknown[]).length > 0) &&
    Array.isArray(value.relatedIssues) && value.relatedIssues.every(item => record(item) && isEntityId(item.id) && string(item.title)) &&
    Array.isArray(value.activities) && value.activities.every(isPublicContext);
}
export function isKnowledgePayload(path: string, value: unknown): boolean | null {
  const parts = path.split("?")[0].split("/");
  const query = new URLSearchParams(path.split("?")[1] || "");
  const versionMatches = (field: string) => !query.has("version") || (record(value) && value[field] === query.get("version"));
  if (parts[3] === "people" && parts[5] === "profile") return profile(value);
  if (parts[3] === "people" && parts[5] === "timeline") return record(value) && isEntityId(value.id) && Array.isArray(value.items) && value.items.length <= 100 && value.items.every(isPublicContext) && (value.nextCursor === null || (string(value.nextCursor) && value.nextCursor.length > 0 && value.nextCursor.length <= 600));
  if (parts[3] === "activities" && parts[5] === "context") return isPublicContext(value) && versionMatches("eventVersion");
  if (parts[3] === "documents") return document(value) && versionMatches("version") && (!query.has("extractionVersion") || (record(value) && value.extractionVersion === query.get("extractionVersion")));
  if (parts[3] === "evidence") return evidence(value);
  if (parts[3] === "bills" && parts[5] === "lineage") return record(value) && isEntityId(value.id) && Array.isArray(value.items) && value.items.every(relation);
  if (parts[3] === "issues" && parts[5] === "timeline") return record(value) && isEntityId(value.id) && Array.isArray(value.items) && value.items.every(isPublicContext) && (value.nextCursor === undefined || value.nextCursor === null || string(value.nextCursor));
  return null;
}
