"use client";
import Link from "next/link";
import { useEffect, useState, type FormEvent } from "react";
import { useInterests } from "./interests";
export function LoginForm() {
  const { authenticated } = useInterests();
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setMessage("");
    try {
      const response = await fetch("/api/v1/auth/request-link", { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email: email.trim() }), signal: AbortSignal.timeout(10000) });
      if (!response.ok) throw new Error("failed");
      setMessage("로그인 링크를 요청했습니다. 메일이 도착하면 링크를 열어 로그인해 주세요.");
    } catch { setMessage("로그인 링크를 요청하지 못했습니다. 잠시 후 다시 시도해 주세요."); }
    finally { setBusy(false); }
  }
  if (authenticated) return null;
  return <section className="auth-panel"><h2>이메일로 관심 목록 이어보기</h2><p className="muted">로그인하면 다른 기기에서도 관심 목록을 확인하고, 주간·일간 알림을 설정할 수 있습니다.</p><form onSubmit={submit}><label htmlFor="email">이메일 주소</label><div className="auth-row"><input id="email" name="email" type="email" autoComplete="email" placeholder="name@example.com" required maxLength={254} value={email} onChange={event => setEmail(event.target.value)} /><button className="button" disabled={busy}>{busy ? "요청 중…" : "로그인 링크 요청"}</button></div><p role="status" className="form-status">{message}</p></form></section>;
}
export function VerifyLogin() {
  const { reload } = useInterests();
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [complete, setComplete] = useState(false);
  const [message, setMessage] = useState("");
  useEffect(() => {
    const url = new URL(window.location.href);
    setToken(url.searchParams.get("token") || "");
    url.searchParams.delete("token");
    window.history.replaceState(null, "", url.pathname + url.search + url.hash);
  }, []);
  async function verify() {
    setBusy(true);
    try {
      const response = await fetch("/api/v1/auth/verify", { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ token }), signal: AbortSignal.timeout(10000) });
      if (!response.ok) throw new Error("invalid");
      setToken(""); await reload(); setComplete(true); setMessage("로그인했습니다. 관심 목록과 알림 설정을 확인해 주세요.");
    } catch { setMessage("로그인 링크가 만료되었거나 확인할 수 없습니다. 새 링크를 요청해 주세요."); }
    finally { setBusy(false); }
  }
  return <div className="settings-panel"><h1>이메일 로그인 확인</h1><p>로그인 링크를 직접 요청한 경우 아래 버튼을 눌러 로그인해 주세요.</p>{complete ? <Link href="/interests" className="button">내 관심으로 이동</Link> : <button className="button" disabled={busy || !token} onClick={() => void verify()}>{busy ? "확인 중…" : "로그인 확인"}</button>}<p role="status" className="form-status">{message}</p><Link className="text-link" href="/interests">새 로그인 링크 요청 →</Link></div>;
}
export function UnsubscribeNotifications() {
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [complete, setComplete] = useState(false);
  const [message, setMessage] = useState("");
  useEffect(() => {
    const url = new URL(window.location.href);
    setToken(url.searchParams.get("token") || "");
    url.searchParams.delete("token");
    window.history.replaceState(null, "", url.pathname + url.search + url.hash);
  }, []);
  async function unsubscribe() {
    setBusy(true);
    try {
      const response = await fetch("/api/v1/auth/unsubscribe", { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ token }), signal: AbortSignal.timeout(10000) });
      if (!response.ok) throw new Error("failed");
      setToken(""); setComplete(true); setMessage("이메일 알림을 중단했습니다.");
    } catch { setMessage("알림을 중단하지 못했습니다. 링크를 다시 열거나 내 관심 화면에서 알림을 끌 수 있습니다."); }
    finally { setBusy(false); }
  }
  return <div className="settings-panel"><h1>이메일 알림 중단</h1><p>이 링크에 연결된 이메일의 일간·주간 묶음 알림을 중단합니다. 관심 목록은 유지됩니다.</p>{!complete && <button className="button" disabled={busy || !token} onClick={() => void unsubscribe()}>{busy ? "중단 중…" : "이메일 알림 중단"}</button>}<p role="status" className="form-status">{message}</p><Link href="/interests" className="text-link">내 관심 설정으로 이동 →</Link></div>;
}
