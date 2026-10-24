import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ActivityFeed } from "@/components/feed";
import { InterestsProvider } from "@/components/interests";
const item = { id: "mine", type: "bill", title: "내 관심의 기록", summary: "", stage: "proposed", personIds: ["p1"], topics: ["housing"], billId: "b1", occurredAt: null, publishedAt: "2026-10-01T00:00:00Z", collectedAt: "2026-10-01T01:00:00Z", sourceUrl: "https://example.test/", evidence: [], votes: [], coverage: "공개 기록", corrected: false, version: "1" };
afterEach(() => vi.unstubAllGlobals());
describe("personalized first view", () => {
  it("defaults to resolved interests and preserves the user's latest-tab selection", async () => {
    vi.stubGlobal("fetch", async (url: string) => url === "/api/v1/me" ? Response.json({ authenticated: true, csrfToken: "csrf", follows: [{ kind: "person", targetId: "p1" }], frequency: "weekly" }) : Response.json({ items: [item] }));
    render(<InterestsProvider><ActivityFeed initial={{ status: "ok", data: { items: [] } }} filtered={false} /></InterestsProvider>);
    await waitFor(() => expect(screen.getByText("내 관심의 기록")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "최신 변화" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "최신 변화" })).toHaveAttribute("aria-pressed", "true"));
    expect(screen.queryByText("내 관심의 기록")).not.toBeInTheDocument();
  });
});
