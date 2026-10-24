import { afterEach, describe, expect, it, vi } from "vitest";
const getIssue = vi.hoisted(() => vi.fn());
const getEditorialIssue = vi.hoisted(() => vi.fn());
const canReadEditorial = vi.hoisted(() => vi.fn());
afterEach(() => vi.clearAllMocks());
vi.mock("@/lib/server-api", () => ({ getIssue, getIssueTimeline: vi.fn() }));
vi.mock("@/lib/editorial-data", () => ({ getEditorialIssue, canReadEditorial }));
import IssuePage, { generateMetadata } from "@/app/issues/[id]/page";
import { EditorialIssueView } from "@/components/editorial-issue";
import { ApiNotice } from "@/components/api-notice";

describe("exact editorial issue routes", () => {
  it("reads an exact local dossier without requesting an authenticated or unavailable backend", async () => {
    const issue = { id: "amendment-process-20261017", title: "준비한 해설", summary: "원문 근거", reviewStatus: "human-review-pending" };
    getEditorialIssue.mockReturnValueOnce(issue);
    canReadEditorial.mockReturnValueOnce(true);
    const page = await IssuePage({ params: Promise.resolve({ id: issue.id }), searchParams: Promise.resolve({}) });
    expect(page.type).toBe(EditorialIssueView);
    expect(page.props.issue).toEqual(issue);
    expect(getIssue).not.toHaveBeenCalled();
  });
  it("keeps a different issue's genuine backend failure instead of substituting a dossier", async () => {
    getEditorialIssue.mockReturnValueOnce(undefined);
    getIssue.mockResolvedValueOnce({ status: "offline" });
    const page = await IssuePage({ params: Promise.resolve({ id: "different-issue" }), searchParams: Promise.resolve({}) });
    expect(page.type).toBe(ApiNotice);
    expect(page.props.status).toBe("offline");
    expect(getIssue).toHaveBeenCalledWith("different-issue");
  });
  it("keeps human review pending previews out of search indexing", async () => {
    getEditorialIssue.mockReturnValueOnce({ id: "draft", title: "해설 초안", summary: "원문 확인", reviewStatus: "human-review-pending" });
    canReadEditorial.mockReturnValueOnce(true);
    const metadata = await generateMetadata({ params: Promise.resolve({ id: "draft" }), searchParams: Promise.resolve({}) });
    expect(metadata.robots).toEqual({ index: false, follow: true });
  });
});


describe("unpublished exact editorial IDs", () => {
  it("returns 404 without falling through to the public API", async () => {
    getEditorialIssue.mockReturnValueOnce({ id: "draft", reviewStatus: "human-review-pending" });
    canReadEditorial.mockReturnValueOnce(false);
    await expect(IssuePage({ params: Promise.resolve({ id: "draft" }), searchParams: Promise.resolve({}) })).rejects.toThrow("NEXT_HTTP_ERROR_FALLBACK;404");
    expect(getIssue).not.toHaveBeenCalled();
  });
  it("returns 404 metadata without exposing a pending title or summary", async () => {
    getEditorialIssue.mockReturnValueOnce({ id: "draft", title: "private pending title", reviewStatus: "human-review-pending" });
    canReadEditorial.mockReturnValueOnce(false);
    await expect(generateMetadata({ params: Promise.resolve({ id: "draft" }), searchParams: Promise.resolve({}) })).rejects.toThrow("NEXT_HTTP_ERROR_FALLBACK;404");
    expect(getIssue).not.toHaveBeenCalled();
  });
});
