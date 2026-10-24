"use client";
import Link from "next/link";
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import type { Follow, FollowKind, Preferences } from "@/lib/contracts";
import { TOPICS } from "@/lib/format";
import { EMPTY_PREFERENCES, parsePreferences, STORAGE_KEY, toggleFollow } from "@/lib/preferences";
interface InterestsContext extends Preferences {
  authenticated: boolean; loading: boolean; busy: boolean; message: string;
  update: (preferences: Preferences) => Promise<boolean>;
  reload: () => Promise<void>;
  logout: () => Promise<void>;
  emitUsage: (event: "activity_opened" | "follow_saved" | "relevance", rating?: boolean) => Promise<void>;
}
const Context = createContext<InterestsContext | null>(null);
export function InterestsProvider({ children }: { children: ReactNode }) {
  const [preferences, setPreferences] = useState<Preferences>(EMPTY_PREFERENCES);
  const [authenticated, setAuthenticated] = useState(false);
  const [csrfToken, setCsrfToken] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const response = await fetch("/api/v1/me", { credentials: "same-origin", cache: "no-store", signal: AbortSignal.timeout(10000) });
      if (!response.ok) throw new Error("unavailable");
      const data = await response.json();
      if (typeof data.authenticated !== "boolean") throw new Error("invalid session");
      setAuthenticated(data.authenticated);
      setCsrfToken(typeof data.csrfToken === "string" ? data.csrfToken : "");
      if (data.authenticated) setPreferences(parsePreferences(JSON.stringify(data)));
    } catch { setMessage("계정 연결 상태를 확인하지 못했습니다. 관심 목록은 이 기기에서 확인할 수 있습니다."); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => {
    try { setPreferences(parsePreferences(localStorage.getItem(STORAGE_KEY))); } catch { setMessage("이 브라우저에서는 관심 목록을 저장할 수 없습니다."); }
    void reload();
  }, [reload]);
  const emitUsage = useCallback(async (event: "activity_opened" | "follow_saved" | "relevance", rating?: boolean) => {
    if (!authenticated || !csrfToken || loading) return;
    try {
      await fetch("/api/v1/usage", { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json", "X-CSRF-Token": csrfToken }, body: JSON.stringify({ event, ...(typeof rating === "boolean" ? { rating } : {}) }), signal: AbortSignal.timeout(5000) });
    } catch { /* Optional aggregate measurement must not interrupt the user flow. */ }
  }, [authenticated, csrfToken, loading]);
  async function update(next: Preferences): Promise<boolean> {
    if (busy || loading) return false;
    if (next.follows.length > 20) { setMessage("베타에서는 관심 대상을 최대 20개 등록할 수 있습니다."); return false; }
    setBusy(true); setMessage("");
    try {
      if (authenticated) {
        if (!csrfToken) throw new Error("unauthorized");
        const response = await fetch("/api/v1/me/follows", { method: "PUT", credentials: "same-origin", headers: { "Content-Type": "application/json", "X-CSRF-Token": csrfToken }, body: JSON.stringify(next), signal: AbortSignal.timeout(10000) });
        if (!response.ok) throw new Error("failed");
      } else { localStorage.setItem(STORAGE_KEY, JSON.stringify(next)); }
      setPreferences(next);
      if (authenticated && JSON.stringify(next.follows) !== JSON.stringify(preferences.follows)) void emitUsage("follow_saved");
      return true;
    } catch { setMessage("설정을 저장하지 못했습니다. 연결을 확인한 뒤 다시 시도해 주세요."); return false; }
    finally { setBusy(false); }
  }
  async function logout() {
    if (busy || !csrfToken) return;
    setBusy(true);
    try {
      const response = await fetch("/api/v1/auth/logout", { method: "POST", credentials: "same-origin", headers: { "X-CSRF-Token": csrfToken }, signal: AbortSignal.timeout(10000) });
      if (!response.ok) throw new Error("failed");
      setAuthenticated(false); setCsrfToken(""); setPreferences(EMPTY_PREFERENCES); localStorage.removeItem(STORAGE_KEY); setMessage("로그아웃했습니다.");
    } catch { setMessage("로그아웃하지 못했습니다. 다시 시도해 주세요."); }
    finally { setBusy(false); }
  }
  return <Context.Provider value={{ ...preferences, authenticated, loading, busy, message, update, reload, logout, emitUsage }}>{children}</Context.Provider>;
}
export function useInterests() {
  const context = useContext(Context);
  if (!context) throw new Error("InterestsProvider is required");
  return context;
}
export function FollowButton({ kind, targetId, label }: { kind: FollowKind; targetId: string; label: string }) {
  const { follows, frequency, update, loading, busy } = useInterests();
  const selected = follows.some(follow => follow.kind === kind && follow.targetId === targetId);
  return <button className={`follow-button ${selected ? "selected" : ""}`} aria-label={`${label} 관심 ${selected ? "해제" : "등록"}`} aria-pressed={selected} disabled={loading || busy} onClick={() => void update({ follows: toggleFollow(follows, { kind, targetId }), frequency })}><span aria-hidden="true">{selected ? "✓" : "+"}</span> {selected ? "관심 등록됨" : "관심 등록"}</button>;
}
function followLink(follow: Follow): string {
  const base = follow.kind === "person" ? "/people/" : follow.kind === "bill" ? "/bills/" : follow.kind === "issue" ? "/issues/" : "/?topic=";
  return `${base}${encodeURIComponent(follow.targetId)}`;
}
export function InterestsSettings() {
  const { follows, frequency, authenticated, loading, busy, message, update, logout } = useInterests();
  const [deviceFollows, setDeviceFollows] = useState<Follow[]>([]);
  useEffect(() => {
    if (!authenticated) { setDeviceFollows([]); return; }
    try { setDeviceFollows(parsePreferences(localStorage.getItem(STORAGE_KEY)).follows); } catch { setDeviceFollows([]); }
  }, [authenticated]);
  const unsaved = deviceFollows.filter(local => !follows.some(saved => saved.kind === local.kind && saved.targetId === local.targetId));
  async function importDeviceFollows() {
    if (await update({ follows: [...follows, ...unsaved], frequency })) {
      try { localStorage.removeItem(STORAGE_KEY); } catch { /* Account save succeeded even if browser storage is restricted. */ }
      setDeviceFollows([]);
    }
  }
  return <section className="settings-panel">
    <h2>내 관심 목록</h2>
    <p>{authenticated ? "관심 대상의 새로운 변화만 묶어서 받아보세요." : "이 기기에 관심 목록이 저장됩니다. 이메일 알림은 로그인 후 설정할 수 있습니다."}</p>
    {authenticated && unsaved.length > 0 && <div className="notice"><p>로그인 전에 이 기기에 저장한 관심 대상 {unsaved.length}개가 있습니다. 직접 가져오면 현재 계정의 목록에 추가합니다.</p><button className="button secondary" disabled={loading || busy} onClick={() => void importDeviceFollows()}>이 기기의 관심 목록 가져오기</button></div>}
    <div className="interest-topics">{Object.entries(TOPICS).map(([id, label]) => <div className="interest-choice" key={id}><span>{label}</span><FollowButton kind="topic" targetId={id} label={label} /></div>)}</div>
    {follows.length > 0 ? <ul className="follow-list">{follows.map(follow => <li key={`${follow.kind}:${follow.targetId}`}><Link href={followLink(follow)}>{TOPICS[follow.targetId] || `${follow.kind === "person" ? "인물" : follow.kind === "bill" ? "법안" : "이슈"} · ${follow.targetId}`}</Link><button className="text-button" disabled={loading || busy} onClick={() => void update({ follows: toggleFollow(follows, follow), frequency })}>해제</button></li>)}</ul> : <p className="muted">아직 등록된 관심 대상이 없습니다. 인물·법안·이슈 페이지에서 등록할 수 있습니다.</p>}
    <p className="muted">관심 대상 최대 20개 · 정치성향 분석이나 광고 판매에 사용하지 않습니다.</p>
    {authenticated && <fieldset disabled={loading || busy}><legend>이메일 묶음 알림</legend>{(["weekly", "daily", "off"] as const).map(value => <label className="radio-label" key={value}><input type="radio" name="frequency" checked={frequency === value} onChange={() => void update({ follows, frequency: value })} />{value === "weekly" ? "주간" : value === "daily" ? "일간" : "알림 받지 않기"}</label>)}</fieldset>}
    <p role="status" className="form-status">{message}</p>
    {authenticated && <button className="text-button" disabled={busy} onClick={() => void logout()}>로그아웃</button>}
  </section>;
}
