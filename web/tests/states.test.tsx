import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ApiNotice } from "@/components/api-notice";
import { VoteTable } from "@/components/vote-table";
describe("honest empty and missing records", () => {
  it("distinguishes outage from no matching public records", () => {
    render(<ApiNotice status="offline" />);
    expect(screen.getByText("기록 서버에 연결할 수 없습니다")).toBeInTheDocument();
    expect(screen.queryByText("공개된 기록이 없습니다")).not.toBeInTheDocument();
  });
  it("keeps unknown votes unknown and only renders recorded absence", () => {
    render(<VoteTable votes={[{ personId: "p1", name: "의원 A", sessionId: "s1", result: "unknown" }, { personId: "p2", name: "의원 B", sessionId: "s1", result: "absent" }]} />);
    expect(screen.getByText("개인별 기록 미확인")).toBeInTheDocument();
    expect(screen.getAllByText("불참")).toHaveLength(1);
  });
});
