import { afterEach, describe, expect, it, vi } from "vitest";
import StartPage, { generateMetadata } from "@/app/start/page";
import type { EditorialIssue } from "@/lib/editorial";
import { editorialPreviewEnabled, getVisibleEditorialIssues, getEditorialIssue, canReadEditorial } from "@/lib/editorial-data";
vi.mock("@/data/editorial-issues.json", async importOriginal => {
  const { default: data } = await importOriginal<{ default: { issues: EditorialIssue[] } }>();
  return { default: { issues: data.issues.map(issue => ({ ...issue, reviewStatus: "human-review-pending", reviewedAt: undefined })) } };
});
afterEach(() => vi.unstubAllEnvs());
describe("server editorial publication boundary", () => {
  it("keeps pending dossiers out of the default public list", () => {
    vi.stubEnv("EDITORIAL_PREVIEW_ENABLED", "");
    vi.stubEnv("PUBLIC_BASE_URL", "https://example.test");
    expect(getVisibleEditorialIssues()).toEqual([]);
    expect(StartPage().props.issues).toEqual([]);
    expect(generateMetadata().description).toContain("첫 해설");
    const draft = getEditorialIssue("amendment-process-20261017")!;
    expect(canReadEditorial(draft)).toBe(false);
    expect(canReadEditorial({ ...draft, reviewStatus: "reviewed" })).toBe(false);
    expect(canReadEditorial({ ...draft, reviewStatus: "reviewed", reviewedAt: "2026-10-17T18:00:00+09:00" })).toBe(true);
  });
  it("shows pending dossiers only under an explicit fixed HTTP loopback preview", () => {
    for (const base of ["http://localhost:14202", "http://127.0.0.1:14202", "http://[::1]:14202"]) {
      vi.stubEnv("EDITORIAL_PREVIEW_ENABLED", "true");
      vi.stubEnv("PUBLIC_BASE_URL", base);
      expect(editorialPreviewEnabled()).toBe(true);
      expect(getVisibleEditorialIssues()).toHaveLength(3);
      expect(canReadEditorial(getEditorialIssue("amendment-process-20261017")!)).toBe(true);
    }
  });
  it("never opens preview on a public origin, lookalike host or non-origin base", () => {
    vi.stubEnv("EDITORIAL_PREVIEW_ENABLED", "true");
    for (const base of ["https://example.test", "http://example.test", "https://localhost:14202", "http://localhost.evil.test", "http://localhost:14202/preview", "http://user:pass@localhost:14202", ""]) {
      vi.stubEnv("PUBLIC_BASE_URL", base);
      expect(editorialPreviewEnabled()).toBe(false);
      expect(getVisibleEditorialIssues()).toEqual([]);
    }
  });
});
