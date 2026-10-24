import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { PersonProfileDetails } from "@/components/knowledge-panels";
import type { PersonProfile } from "@/lib/knowledge-contracts";

const profile: PersonProfile = {
  id: "test-person-dates",
  name: "검사용 인물",
  kind: "person",
  facts: [],
  tenures: [{
    organizationId: "test-organization",
    organizationName: "검사용 기관",
    position: "기록된 직위",
    party: null,
    validFrom: "2024-05-30",
    validUntil: "2026-05-29",
    observedAt: "2026-10-20T00:00:00Z",
    evidenceIds: ["test-evidence-dates"],
  }],
  relatedIssues: [],
  activities: [],
};

describe("person office observation and effective period", () => {
  it.each([
    {
      label: "both effective dates are known",
      validFrom: "2024-05-30",
      validUntil: "2026-05-29",
      period: "효력 기간 · 2024. 05. 30. ~ 2026. 05. 29.",
    },
    {
      label: "the end date is unknown",
      validFrom: "2024-05-30",
      validUntil: null,
      period: "효력 기간 · 2024. 05. 30. ~ 종료일 미확인",
    },
    {
      label: "the start date is unknown",
      validFrom: null,
      validUntil: "2026-05-29",
      period: "효력 기간 · 시작일 미확인 ~ 2026. 05. 29.",
    },
    {
      label: "the effective period is unknown",
      validFrom: null,
      validUntil: null,
      period: "효력 기간 · 시작일 미확인 ~ 종료일 미확인",
    },
  ])("keeps the observation separate when $label", ({ validFrom, validUntil, period }) => {
    render(<PersonProfileDetails profile={{
      ...profile,
      tenures: [{ ...profile.tenures[0], validFrom, validUntil }],
    }} />);

    expect(screen.getByText("자료 관측일 · 2026. 10. 20.")).toBeInTheDocument();
    expect(screen.getByText(period)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "근거 1 →" })).toHaveAttribute("href", "/evidence/test-evidence-dates");
    expect(screen.queryByText(/현직|현재 재직|현재 재임/)).not.toBeInTheDocument();
  });
});
