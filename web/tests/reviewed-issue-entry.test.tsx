import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import sample from "./fixtures/issue-reading-v1-success.json";
const read = vi.hoisted(() => vi.fn());
vi.mock("@/lib/issue-reading-browser", () => ({ readBrowserIssueReading: read }));
vi.mock("@/components/beta", () => ({ MarketingVisit: () => null }));
import { MarketingStart } from "@/components/marketing-start";
beforeEach(() => vi.clearAllMocks());
describe("editor selected entry on the public start page", () => {
  it("shows an exact approved reading link separately from static dossiers", async () => {
    read.mockResolvedValue({ status: "ok", data: { ...sample, issueId: "child-support-advance" } });
    render(<MarketingStart issues={[]} />);
    expect(await screen.findByRole("link", { name: /시험 해설.*쉬운 해설 읽기/ })).toHaveAttribute("href", "/issues/child-support-advance");
  });
  it.each([["not-found", "현재 공개된 선정 해설이 없어요."], ["conflict", "해설의 공개 버전을 다시 확인해 주세요"], ["error", "해설을 불러오지 못했어요"]])("keeps %s separate without showing a private title", async (status, message) => {
    read.mockResolvedValue({ status });
    render(<MarketingStart issues={[]} />);
    expect(await screen.findByText(message, { exact: true })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /시험 해설/ })).not.toBeInTheDocument();
  });
});
