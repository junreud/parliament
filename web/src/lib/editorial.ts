export type EditorialSource = {
  id: string; title: string; publisher: string; url: string; publishedAt: string;
  locator: string; sourceType: "official-record" | "official-position"; usageNote: string;
};
export type EditorialIssue = {
  id: string; title: string; question: string; summary: string; topic: string;
  currentStage: string; nextTrigger: string; checkedAt: string;
  reviewStatus: "human-review-pending" | "reviewed"; reviewedAt?: string;
  background: string[]; facts: string[]; claims: string[]; unknowns: string[];
  timeline: { date: string; title: string; detail: string; sourceIds: string[] }[];
  sources: EditorialSource[]; updates: { date: string; note: string }[];
};
export function isReviewedEditorial(issue: EditorialIssue): boolean {
  return issue.reviewStatus === "reviewed" && Boolean(issue.reviewedAt) && !Number.isNaN(Date.parse(issue.reviewedAt || ""));
}
