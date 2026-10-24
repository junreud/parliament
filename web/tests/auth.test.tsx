import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { LoginForm } from "@/components/auth";
import { InterestsProvider } from "@/components/interests";
afterEach(() => vi.unstubAllGlobals());
describe("email link request", () => {
  it("asks the same-origin backend and reports accepted request rather than delivery", async () => {
    vi.stubGlobal("fetch", async (url: string, init?: RequestInit) => {
      if (url === "/api/v1/me") return Response.json({ authenticated: false });
      expect(url).toBe("/api/v1/auth/request-link");
      expect(JSON.parse(String(init?.body))).toEqual({ email: "reader@example.test" });
      return new Response("", { status: 202 });
    });
    render(<InterestsProvider><LoginForm /></InterestsProvider>);
    fireEvent.change(screen.getByLabelText("이메일 주소"), { target: { value: "reader@example.test" } });
    fireEvent.click(screen.getByRole("button", { name: "로그인 링크 요청" }));
    await waitFor(() => expect(screen.getByText("로그인 링크를 요청했습니다. 메일이 도착하면 링크를 열어 로그인해 주세요.")).toBeInTheDocument());
  });
});

describe("email unsubscribe confirmation", () => {
  it("does not unsubscribe on page load and removes token from the browser address", async () => {
    window.history.replaceState(null, "", "/unsubscribe?token=private-token");
    let sent = false;
    vi.stubGlobal("fetch", async (url: string) => {
      if (url === "/api/v1/me") return Response.json({ authenticated: false });
      sent = true;
      return new Response(null, { status: 204 });
    });
    const { UnsubscribeNotifications } = await import("@/components/auth");
    render(<UnsubscribeNotifications />);
    await waitFor(() => expect(screen.getByRole("button", { name: "이메일 알림 중단" })).not.toBeDisabled());
    expect(window.location.search).toBe("");
    expect(sent).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "이메일 알림 중단" }));
    await waitFor(() => expect(screen.getByText("이메일 알림을 중단했습니다.")).toBeInTheDocument());
  });
});
