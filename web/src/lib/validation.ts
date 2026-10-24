import type { Activity } from "./contracts";
import { isLawPage } from "./law-records";
function record(value: unknown): value is Record<string, unknown> { return value !== null && typeof value === "object" && !Array.isArray(value); }
function strings(value: unknown): value is string[] { return Array.isArray(value) && value.every(item => typeof item === "string"); }
export function isInstant(value: unknown): value is string { return typeof value === "string" && /^\d{4}-\d{2}-\d{2}T/.test(value) && !Number.isNaN(Date.parse(value)); }
export function isActivity(value: unknown): value is Activity {
  if (!record(value)) return false;
  return typeof value.corrected === "boolean" && (value.occurredAt === null || isInstant(value.occurredAt)) && isInstant(value.publishedAt) && isInstant(value.collectedAt) && (value.changedAt === undefined || isInstant(value.changedAt)) && ["id", "type", "title", "stage", "collectedAt", "sourceUrl", "coverage", "version"].every(key => typeof value[key] === "string") && (value.summary === null || typeof value.summary === "string") && strings(value.personIds) && strings(value.topics) && Array.isArray(value.evidence) && value.evidence.every(item => record(item) && ["id", "sourceUrl", "locator", "sourceVersion"].every(key => typeof item[key] === "string") && (item.excerpt === null || typeof item.excerpt === "string")) && Array.isArray(value.votes) && value.votes.every(item => record(item) && ["personId", "name", "result", "sessionId"].every(key => typeof item[key] === "string")) && (value.billId === null || typeof value.billId === "string");
}
export function isApiPayload(path: string, value: unknown): boolean {
  if (!record(value)) return false;
  const segments = path.split("?")[0].split("/");
  const resource = segments[3];
  const detail = Boolean(segments[4]);
  if (resource === "laws") return !detail && isLawPage(value);
  if (resource === "activities" && segments[5] === "history") return Array.isArray(value.items) && value.items.every(item => record(item) && typeof item.version === "string" && isInstant(item.reviewedAt) && typeof item.corrected === "boolean" && (item.correctionReason === null || typeof item.correctionReason === "string"));
  function validItem(item: unknown): boolean {
    if (resource === "activities" || resource === "search") return isActivity(item);
    if (!record(item)) return false;
    if (resource === "coverage") return typeof item.source === "string" && typeof item.status === "string";
    return typeof item.id === "string" && typeof item[resource === "people" ? "name" : "title"] === "string";
  }
  if (resource === "me" || resource === "auth") return true;
  if (!detail) return (value.nextCursor === undefined || value.nextCursor === null || typeof value.nextCursor === "string") && Array.isArray(value.items) && value.items.every(validItem);
  return validItem(value) && (value.activities === undefined || (Array.isArray(value.activities) && value.activities.every(isActivity)));
}
