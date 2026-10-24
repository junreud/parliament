import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ParticipantList, BillRelations, ContextTimeline, PersonActivities } from "@/components/knowledge-panels";
import type { PublicContext } from "@/lib/knowledge-contracts";

const context: PublicContext = {
  eventId: "event-1", eventVersion: "version-1", changeKind: "new_record",
  activity: { id: "event-1", version: "version-1", type: "announcement", title: "예정 간담회 발표", summary: null, stage: "scheduled", personIds: ["person-1"], topics: [], billId: null, occurredAt: null, publishedAt: "2026-08-13T00:00:00Z", collectedAt: "2026-10-08T00:00:00Z", sourceUrl: "https://www.mogef.go.kr/record", evidence: [], votes: [], coverage: "공식 발표", corrected: false },
  participants: [{ personId: "person-1", name: "원민경", role: "scheduled_participant", evidenceIds: ["e1"], organizationAtTime: "발표 당시 기관", positionAtTime: "장관" }],
  documents: [], evidence: [], relations: []
};

describe("verified roles and temporal context", () => {
  it("displays planned participation and the position at the time without claiming an outcome", () => {
    render(<ParticipantList participants={context.participants} />);
    expect(screen.getByText("참여 예정")).toBeInTheDocument();
    expect(screen.getByText("발표 당시 기관 · 장관")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "원민경" })).toHaveAttribute("href", "/people/person-1");
    expect(screen.queryByText("개최 완료")).not.toBeInTheDocument();
  });

  it("keeps bill originals and alternatives separate with evidence links", () => {
    render(<BillRelations billId="bill-original" items={[{ id: "r1", subjectId: "bill-original", objectId: "bill-alternative", type: "incorporated_into_alternative", decision: "approved", reason: "통합 대안 원문으로 확인", evidenceIds: ["e1"] }]} />);
    expect(screen.getByRole("link", { name: "bill-alternative" })).toHaveAttribute("href", "/bills/bill-alternative");
    expect(screen.getByText("대안에 통합됨")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "근거 1 →" })).toHaveAttribute("href", "/evidence/e1");
  });

  it("shows the related bill title and recorded stage instead of its internal identifier", () => {
    render(<BillRelations billId="bill-original" items={[{ id: "r1", subjectId: "bill-original", objectId: "bill-alternative", type: "incorporated_into_alternative", decision: "approved", reason: "통합 대안 원문으로 확인", evidenceIds: ["e1"] }]} billSummaries={{ "bill-alternative": { status: "ok", data: { title: "양육비 이행법 위원회 대안", stage: "passed" } } }} />);
    expect(screen.getByRole("link", { name: "양육비 이행법 위원회 대안" })).toHaveAttribute("href", "/bills/bill-alternative");
    expect(screen.getByText("의결")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "bill-alternative" })).not.toBeInTheDocument();
  });

  it.each(["offline", "not-found"] as const)("keeps the related bill stage unknown when its lookup is %s", status => {
    render(<BillRelations billId="bill-original" items={[{ id: "r1", subjectId: "bill-original", objectId: "bill-alternative", type: "incorporated_into_alternative", decision: "approved", reason: "통합 대안 원문으로 확인", evidenceIds: ["e1"] }]} billSummaries={{ "bill-alternative": { status } }} />);
    expect(screen.getByText("단계 미확인")).toBeInTheDocument();
    expect(screen.getByText(/식별자: bill-alternative/)).toBeInTheDocument();
    expect(screen.queryByText("의결")).not.toBeInTheDocument();
  });

  it("labels a timeline with publication time when occurrence is unknown and fixes the event version", () => {
    render(<ContextTimeline items={[context]} />);
    expect(screen.getByText(/공개일 기준/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "예정 간담회 발표" })).toHaveAttribute("href", "/activities/event-1?version=version-1");
  });

  it("filters person activities by confirmed role and excludes name-only mentions", () => {
    render(<PersonActivities personId="person-1" contexts={[context, { ...context, eventId: "mention-event", participants: [] }]} />);
    expect(screen.getAllByRole("link", { name: "예정 간담회 발표" })).toHaveLength(1);
    fireEvent.change(screen.getByLabelText("활동 역할"), { target: { value: "lead_sponsor" } });
    expect(screen.queryByRole("link", { name: "예정 간담회 발표" })).not.toBeInTheDocument();
    expect(screen.getByText("이 역할로 확인된 활동이 없습니다.")).toBeInTheDocument();
  });

  it("shows a confirmed planned date separately from publication and never turns it into occurrence", () => {
    render(<ContextTimeline items={[{ ...context, scheduledAt: "2026-08-20T00:00:00Z", scheduledPrecision: "date" }]} />);
    expect(screen.getByText(/공개일 기준/)).toBeInTheDocument();
    expect(screen.getByText(/예정일:/)).toBeInTheDocument();
    expect(screen.queryByText(/발생일 기준/)).not.toBeInTheDocument();
  });
});
