import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import fixture from "./fixtures/issue-reading-v1-success.json";
import type { IssueReading } from "@/lib/issue-reading";
import { PublicIssueReading } from "@/components/public-issue-reading";
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: vi.fn() }) }));
beforeEach(() => { sessionStorage.clear(); history.replaceState({}, ""); });
describe("public reading content", () => {
  it("uses Korean evidence links and approved related people without matching paraphrased names", () => {
    render(<PublicIssueReading id="test-issue" result={{ status: "ok", data: fixture as IssueReading }} />);
    const evidence = screen.getAllByRole("link", { name: /근거 \d+ →/, hidden: true });
    expect(evidence).toHaveLength(4); // summary, stage, background, and the fact inside the disclosure
    for (const link of evidence) expect(link).toHaveAttribute("href", "/evidence/test-evidence");
    expect(screen.getByRole("link", { name: "관련 인물 · 합성 인물 →" })).toHaveAttribute("href", "/people/test-person");
    expect(screen.getByRole("heading", { name: "시험 해설" })).toBeInTheDocument();
  });
  it.each(["conflict", "error", "invalid", "not-found"] as const)("does not show old content when status is %s", status => {
    render(<PublicIssueReading id="test-issue" result={{ status }} />);
    expect(screen.queryByText("시험 배경")).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /관련 인물/ })).not.toBeInTheDocument();
  });
});
