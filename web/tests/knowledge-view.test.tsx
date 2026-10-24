import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MentionText, EvidenceView } from "@/components/knowledge-evidence";
import type { KnowledgeEvidence, Mention } from "@/lib/knowledge-contracts";

const approved: Mention = { id: "m1", surface: "김미애", start: 1, end: 4, personId: "person-kim", decision: "approved" };
const evidence: KnowledgeEvidence = {
  id: "e1", documentId: "d1", documentVersion: "raw-a", extractionVersion: "extract-a", segmentId: "s1",
  start: 1, end: 4, excerpt: "김미애", before: "🙂", after: "가 발의했다.", mentions: [approved],
  sourceUrl: "https://opinion.lawmaking.go.kr/record", title: "의안 원문", locator: "PDF 2쪽"
};

describe("version-pinned evidence and person mentions", () => {
  it("uses Unicode code points so a supplementary character cannot shift a person's link", () => {
    render(<MentionText text="🙂김미애가 발의했다." mentions={[approved]} />);
    expect(screen.getByRole("link", { name: "김미애" })).toHaveAttribute("href", "/people/person-kim");
    screen.getByRole("link", { name: "김미애" }).focus();
    expect(screen.getByRole("link", { name: "김미애" })).toHaveFocus();
    expect(screen.getByText(/가 발의했다/).textContent).toBe("🙂김미애가 발의했다.");
  });

  it("leaves pending names and overlapping or mismatched ranges as original plain text", () => {
    const { rerender } = render(<MentionText text="🙂김미애가 발의했다." mentions={[{ ...approved, decision: "pending", personId: null }]} />);
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    rerender(<MentionText text="🙂김미애가 발의했다." mentions={[approved, { ...approved, id: "m2", start: 2 }]} />);
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    expect(screen.getByText("🙂김미애가 발의했다.")).toBeInTheDocument();
    rerender(<MentionText text="🙂김미애가 발의했다." mentions={[{ ...approved, surface: "다른 이름" }]} />);
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("preserves unsafe HTML as text and refuses an invalid person ID", () => {
    render(<MentionText text="<script>김미애</script>" mentions={[{ ...approved, start: 8, end: 11, personId: "javascript:alert(1)" }]} />);
    expect(document.querySelector("script")).toBeNull();
    expect(screen.getByText("<script>김미애</script>")).toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("maps evidence excerpt offsets back to the fixed segment and opens document at the original version", () => {
    render(<EvidenceView evidence={evidence} />);
    expect(screen.getByRole("link", { name: "김미애" })).toHaveAttribute("href", "/people/person-kim");
    expect(screen.getByText("🙂")).toBeInTheDocument();
    expect(screen.getByText("가 발의했다.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "이 버전의 문서 보기 →" })).toHaveAttribute("href", "/documents/d1?version=raw-a&extractionVersion=extract-a");
    expect(screen.getByText(/extract-a/)).toBeInTheDocument();
  });
});
