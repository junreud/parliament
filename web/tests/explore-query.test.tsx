import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { readApi } from "@/lib/api";
import ExplorePage from "@/app/explore/page";
vi.mock("@/lib/api", () => ({ readApi: vi.fn() }));

describe("bounded graph query", () => {
  beforeEach(() => vi.mocked(readApi).mockReset());

  it("rejects an invalid identity or kind without querying a different political record", async () => {
    render(await ExplorePage({ searchParams: Promise.resolve({ rootKind: "private", rootId: "person-1" }) }));
    expect(readApi).not.toHaveBeenCalled();
    expect(screen.getByText("유효한 인물·기록의 주소를 선택해 주세요.")).toBeInTheDocument();
  });

  it("bounds depth and rejects arbitrary relation filters before building a request", async () => {
    vi.mocked(readApi).mockResolvedValue({ status: "offline" });
    render(await ExplorePage({ searchParams: Promise.resolve({ rootKind: "person", rootId: "person-1", depth: "99", relationType: "private" }) }));
    expect(readApi).toHaveBeenCalledWith("/api/v1/knowledge/graph?rootKind=person&rootId=person-1&depth=1&limit=40");
    expect(screen.getByLabelText("연결 깊이")).toHaveValue("1");
    expect(screen.getByRole("status")).toHaveTextContent("기록 서버에 연결할 수 없습니다");
  });
});
