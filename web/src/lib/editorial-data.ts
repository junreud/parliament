import "server-only";
import data from "@/data/editorial-issues.json";
import { isReviewedEditorial, type EditorialIssue } from "./editorial";
import { REPRESENTATIVE_ISSUE_ID } from "./issue-reading";
export const editorialIssues = data.issues as EditorialIssue[];
export function editorialPreviewEnabled(): boolean {
  if (process.env.EDITORIAL_PREVIEW_ENABLED !== "true" || !process.env.PUBLIC_BASE_URL) return false;
  try {
    const base = new URL(process.env.PUBLIC_BASE_URL);
    return base.protocol === "http:" && ["localhost", "127.0.0.1", "[::1]"].includes(base.hostname) &&
      !base.username && !base.password && base.pathname === "/" && !base.search && !base.hash;
  } catch { return false; }
}
export function canReadEditorial(issue: EditorialIssue): boolean {
  // This issue is served only after the public reading rechecks its current pins/state.
  return issue.id !== REPRESENTATIVE_ISSUE_ID && (isReviewedEditorial(issue) || editorialPreviewEnabled());
}
export function getVisibleEditorialIssues(): EditorialIssue[] {
  return editorialIssues.filter(canReadEditorial);
}
export function getEditorialIssue(id: string): EditorialIssue | undefined {
  return editorialIssues.find(issue => issue.id === id);
}
