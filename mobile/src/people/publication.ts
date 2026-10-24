import { isActivity } from "../../../web/src/lib/validation";
import type { Bill } from "../../../web/src/lib/contracts";

function object(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}
/** Existing public endpoints are the authority; explicit non-public markers fail closed. */
export function hasPublicApproval(value: unknown): boolean {
  if (!object(value)) return false;
  for (const key of ["visibility", "reviewState", "publicationStatus"]) {
    if (key in value && value[key] !== "published") return false;
  }
  if ("decision" in value && value.decision !== "approved") return false;
  return ["facts", "tenures"].every(
    (key) =>
      !Array.isArray(value[key]) ||
      value[key].every((item) => object(item) && hasPublicApproval(item)),
  );
}
export function isPublicBill(value: unknown): value is Bill {
  return (
    object(value) &&
    hasPublicApproval(value) &&
    typeof value.id === "string" &&
    typeof value.title === "string" &&
    value.title.length > 0 &&
    value.title.length <= 2000 &&
    typeof value.stage === "string" &&
    value.stage.length <= 64 &&
    (value.sourceUrl === undefined ||
      value.sourceUrl === null ||
      typeof value.sourceUrl === "string") &&
    (value.activities === undefined ||
      (Array.isArray(value.activities) &&
        value.activities.every(isActivity))) &&
    (value.votes === undefined ||
      (Array.isArray(value.votes) &&
        value.votes.every(
          (v) =>
            object(v) &&
            ["personId", "name", "result", "sessionId"].every(
              (k) => typeof v[k] === "string",
            ),
        )))
  );
}
export function isLineageFor(id: string, value: unknown): boolean {
  return (
    object(value) &&
    value.id === id &&
    Array.isArray(value.items) &&
    value.items.length <= 100 &&
    value.items.every(
      (item) =>
        object(item) &&
        item.type === "incorporated_into_alternative" &&
        item.decision === "approved" &&
        item.subjectId !== item.objectId &&
        (item.subjectId === id || item.objectId === id),
    )
  );
}
