import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { readApi } from "@/lib/api";
import PeoplePage from "@/app/people/page";
vi.mock("@/lib/api", () => ({ readApi: vi.fn() }));
const directory = { items: [{ id: "person-1", name: "검증 인물", kind: "person", position: "의원", organizationId: "org-1", organizationName: "검증 기관", observedAt: "2026-10-09T00:00:00Z" }], nextCursor: "cursor-next" };

describe("nationwide cursor directory", () => {
  beforeEach(() => vi.mocked(readApi).mockReset());

  it("preserves search and organization filters when moving to the next cursor", async () => {
    vi.mocked(readApi).mockResolvedValue({ status: "ok", data: directory });
    render(await PeoplePage({ searchParams: Promise.resolve({ query: "검증", organizationId: "org-1" }) }));
    expect(readApi).toHaveBeenCalledWith("/api/v1/knowledge/people?limit=40&query=%EA%B2%80%EC%A6%9D&organizationId=org-1");
    expect(screen.getByRole("link", { name: /검증 인물/ })).toHaveAttribute("href", "/people/person-1");
    expect(screen.getByRole("link", { name: "다음 인물 더 보기 →" })).toHaveAttribute("href", "/people?query=%EA%B2%80%EC%A6%9D&organizationId=org-1&cursor=cursor-next");
    expect(screen.getByText(/자료 확인일/)).toBeInTheDocument();
  });

  it("preserves legacy browsing when the optional knowledge feature is unavailable", async () => {
    vi.mocked(readApi).mockResolvedValueOnce({ status: "not-found" }).mockResolvedValueOnce({ status: "ok", data: { items: [{ id: "legacy-1", name: "기존 인물", kind: "legislator", organization: "국회", role: "의원" }] } });
    render(await PeoplePage({ searchParams: Promise.resolve({}) }));
    expect(readApi).toHaveBeenLastCalledWith("/api/v1/people");
    expect(screen.getByRole("link", { name: /기존 인물/ })).toHaveAttribute("href", "/people/legacy-1");
    expect(screen.getByText(/기존 공개 명부/)).toBeInTheDocument();
  });

  it("does not silently turn failed collection or a lost cursor into a legacy successful list", async () => {
    vi.mocked(readApi).mockResolvedValue({ status: "offline" });
    render(await PeoplePage({ searchParams: Promise.resolve({ cursor: "cursor-current" }) }));
    expect(readApi).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("status")).toHaveTextContent("연결 실패는 새로운 기록이 없다는 뜻이 아닙니다.");
  });
});
