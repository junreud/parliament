import { afterEach, describe, expect, it, vi } from "vitest";
import type { EditorialIssue } from "@/lib/editorial";
import { REPRESENTATIVE_ISSUE_ID } from "@/lib/issue-reading";

vi.mock("@/data/editorial-issues.json", () => ({
  default: {
    issues: [
      {
        id: "legacy",
        reviewStatus: "reviewed",
        reviewedAt: "2026-10-18T00:00:00Z",
      },
      {
        id: "child-support-advance",
        reviewStatus: "reviewed",
        reviewedAt: "2026-10-24T00:00:00Z",
      },
    ],
  },
}));
import {
  canReadEditorial,
  getEditorialIssue,
  getVisibleEditorialIssues,
} from "@/lib/editorial-data";

afterEach(() => vi.unstubAllEnvs());
describe("API-backed issue publication is rechecked through the public reading", () => {
  it("does not expose a reviewed source copy through the legacy list", () => {
    const issue = getEditorialIssue(REPRESENTATIVE_ISSUE_ID) as EditorialIssue;
    expect(issue.reviewStatus).toBe("reviewed");
    expect(canReadEditorial(issue)).toBe(false);
    expect(getVisibleEditorialIssues().map((item) => item.id)).toEqual([
      "legacy",
    ]);
  });
  it("does not bypass the public reading even under local editorial preview", () => {
    vi.stubEnv("EDITORIAL_PREVIEW_ENABLED", "true");
    vi.stubEnv("PUBLIC_BASE_URL", "http://127.0.0.1:14202");
    expect(canReadEditorial(getEditorialIssue(REPRESENTATIVE_ISSUE_ID)!)).toBe(
      false,
    );
  });
});
