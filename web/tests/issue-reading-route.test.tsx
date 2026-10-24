import { describe, expect, it, vi, beforeEach } from "vitest";
import sample from "./fixtures/issue-reading-v1-success.json";
const getIssueReading = vi.hoisted(() => vi.fn());
const getIssue = vi.hoisted(() => vi.fn());
vi.mock("@/lib/server-api", () => ({ getIssueReading, getIssue, getIssueTimeline: vi.fn() }));
vi.mock("@/lib/editorial-data", () => ({ getEditorialIssue: () => undefined, canReadEditorial: () => false }));
import IssuePage, { generateMetadata } from "@/app/issues/[id]/page";

const props = () => ({ params: Promise.resolve({ id: "child-support-advance" }), searchParams: Promise.resolve({}) });
beforeEach(() => { vi.clearAllMocks(); getIssue.mockResolvedValue({ status: "offline" }); });
describe("representative issue uses the approved reading contract", () => {
  it("renders the reading response without substituting tracking records", async () => {
    const result = { status: "ok", data: { ...sample, issueId: "child-support-advance" } };
    getIssueReading.mockResolvedValue(result);
    const page = await IssuePage(props());
    expect(page.props.result).toEqual(result);
    expect(getIssue).not.toHaveBeenCalled();
    const metadata = await generateMetadata(props());
    expect(metadata.title).toBe(sample.title);
  });
  it("returns 404 for no approved publication without reviving a static or tracking explanation", async () => {
    getIssueReading.mockResolvedValue({ status: "not-found" });
    await expect(IssuePage(props())).rejects.toThrow("NEXT_HTTP_ERROR_FALLBACK;404");
    expect(getIssue).not.toHaveBeenCalled();
  });
  it.each(["conflict", "error", "invalid"])("keeps %s distinct and out of search indexing", async status => {
    getIssueReading.mockResolvedValue({ status });
    const page = await IssuePage(props());
    expect(page.props.result).toEqual({ status });
    expect(getIssue).not.toHaveBeenCalled();
    const metadata = await generateMetadata(props());
    expect(metadata.robots).toEqual({ index: false });
  });
});
