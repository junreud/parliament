import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { InterestsProvider, FollowButton, InterestsSettings } from "@/components/interests";
import { STORAGE_KEY } from "@/lib/preferences";
afterEach(() => { localStorage.clear(); vi.unstubAllGlobals(); });
describe("interest settings", () => {
  it("saves anonymous interests locally and does not promise email delivery", async () => {
    vi.stubGlobal("fetch", async () => new Response('{"authenticated":false,"follows":[],"frequency":"weekly"}'));
    render(<InterestsProvider><FollowButton kind="person" targetId="p1" label="의원 A" /><InterestsSettings /></InterestsProvider>);
    await waitFor(() => expect(screen.getByRole("button", { name: "의원 A 관심 등록" })).not.toBeDisabled());
    fireEvent.click(screen.getByRole("button", { name: "의원 A 관심 등록" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "의원 A 관심 해제" })).toHaveAttribute("aria-pressed", "true"));
    expect(localStorage.getItem(STORAGE_KEY)).toContain('"targetId":"p1"');
    expect(localStorage.getItem(STORAGE_KEY)).not.toContain("csrfToken");
    expect(screen.getByText("이 기기에 관심 목록이 저장됩니다. 이메일 알림은 로그인 후 설정할 수 있습니다.")).toBeInTheDocument();
  });
  it("uses session CSRF for authenticated updates without persisting the session", async () => {
    const requests: Headers[] = [];
    vi.stubGlobal("fetch", async (url: string, init?: RequestInit) => {
      if (url === "/api/v1/me") return new Response('{"authenticated":true,"csrfToken":"private-csrf","follows":[],"frequency":"weekly"}');
      requests.push(new Headers(init?.headers));
      return new Response('{"authenticated":true,"follows":[{"kind":"person","targetId":"p1"}],"frequency":"weekly"}');
    });
    render(<InterestsProvider><FollowButton kind="person" targetId="p1" label="의원 A" /></InterestsProvider>);
    await waitFor(() => expect(screen.getByRole("button")).not.toBeDisabled());
    fireEvent.click(screen.getByRole("button"));
    await waitFor(() => expect(screen.getByRole("button")).toHaveAttribute("aria-pressed", "true"));
    expect(requests[0].get("X-CSRF-Token")).toBe("private-csrf");
    expect(localStorage.getItem(STORAGE_KEY)).toBeNull();
  });
});

describe("explicit anonymous-to-account migration", () => {
  it("keeps device interests until the signed-in user explicitly imports them", async () => {
    localStorage.setItem(STORAGE_KEY, '{"follows":[{"kind":"topic","targetId":"housing"}],"frequency":"weekly"}');
    const saves: unknown[] = [];
    vi.stubGlobal("fetch", async (url: string, init?: RequestInit) => {
      if (url === "/api/v1/me") return Response.json({ authenticated: true, csrfToken: "csrf", follows: [], frequency: "weekly" });
      if (url === "/api/v1/me/follows") saves.push(JSON.parse(String(init?.body)));
      return Response.json({ accepted: true });
    });
    render(<InterestsProvider><InterestsSettings /></InterestsProvider>);
    await waitFor(() => expect(screen.getByRole("button", { name: "이 기기의 관심 목록 가져오기" })).toBeInTheDocument());
    expect(saves).toEqual([]);
    fireEvent.click(screen.getByRole("button", { name: "이 기기의 관심 목록 가져오기" }));
    await waitFor(() => expect(saves).toEqual([{ follows: [{ kind: "topic", targetId: "housing" }], frequency: "weekly" }]));
    expect(localStorage.getItem(STORAGE_KEY)).toBeNull();
  });
});
