"use client";
import Link from "next/link";
import { createContext, useCallback, useContext, useEffect, useRef, useState, type FormEvent } from "react";
import { BETA_SOURCES, resolveBetaVisitKind, isBetaSession, normalizeBetaSource, sendBetaEvent, type BetaEvent, type BetaSession, type BetaSource } from "@/lib/beta";

type BetaContextValue = {
  session: BetaSession; state: "loading" | "available" | "unavailable"; source: BetaSource;
  enroll: (input: { email: string; consent: true; cohort: "friend" | "external"; source: BetaSource }) => Promise<void>;
  withdraw: () => Promise<void>; record: (event: BetaEvent) => void; visit: () => void;
};
const BetaContext = createContext<BetaContextValue | null>(null);
function useBeta() {
  const context = useContext(BetaContext);
  if (!context) throw new Error("BetaProvider is required");
  return context;
}
export function BetaProvider({ children }: { children: React.ReactNode }) {
  const [session, setSession] = useState<BetaSession>({ participating: false });
  const [state, setState] = useState<BetaContextValue["state"]>("loading");
  const [source, setSource] = useState<BetaSource>("direct");
  const acquired = useRef(false);
  useEffect(() => {
    let active = true;
    fetch("/api/v1/beta/session", { referrerPolicy: "no-referrer", credentials: "same-origin", cache: "no-store", signal: AbortSignal.timeout(5000) })
      .then(async response => {
        if (!response.ok) throw new Error("unavailable");
        const data: unknown = await response.json();
        if (!isBetaSession(data)) throw new Error("invalid");
        if (active) { setSession(data); setState("available"); }
      }).catch(() => { if (active) setState("unavailable"); });
    return () => { active = false; };
  }, []);
  const visit = useCallback(() => {
    const params = new URLSearchParams(window.location.search);
    const nextSource = normalizeBetaSource(params);
    if (params.has("utm_source")) setSource(nextSource);
    try { resolveBetaVisitKind(params, window.sessionStorage); }
    catch { /* Reading works when same-tab attribution storage is unavailable. */ }
    if (acquired.current) return;
    acquired.current = true;
    void fetch("/api/v1/beta/acquisition", {
      method: "POST", referrerPolicy: "no-referrer", credentials: "omit", cache: "no-store", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source: nextSource }), signal: AbortSignal.timeout(5000)
    }).catch(() => {});
  }, []);
  const enroll: BetaContextValue["enroll"] = async input => {
    const response = await fetch("/api/v1/beta/participants", {
      method: "POST", referrerPolicy: "no-referrer", credentials: "same-origin", cache: "no-store", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input), signal: AbortSignal.timeout(10000)
    });
    if (response.status !== 201) throw new Error("enrollment-failed");
    const data: unknown = await response.json();
    if (!isBetaSession(data) || !data.participating) throw new Error("invalid-session");
    setSession(data); setState("available");
  };
  const withdraw = async () => {
    if (!session.participating) throw new Error("no-session");
    const response = await fetch("/api/v1/beta/withdraw", {
      method: "POST", referrerPolicy: "no-referrer", credentials: "same-origin", cache: "no-store",
      headers: { "Content-Type": "application/json", "x-csrf-token": session.csrfToken },
      body: "{}", signal: AbortSignal.timeout(10000)
    });
    if (!response.ok) throw new Error("withdrawal-failed");
    setSession({ participating: false });
  };
  const record = useCallback((event: BetaEvent) => {
    try {
      // Recheck expiry on every action; an open tab must not stay a research visit indefinitely.
      const kind = resolveBetaVisitKind(new URLSearchParams(), window.sessionStorage);
      void sendBetaEvent(session, event, kind);
    } catch { /* Skip measurement if attribution storage cannot be read safely. */ }
  }, [session]);
  return <BetaContext.Provider value={{ session, state, source, enroll, withdraw, record, visit }}>{children}</BetaContext.Provider>;
}
export function MarketingVisit() {
  const { visit } = useBeta();
  useEffect(visit, [visit]);
  return null;
}
export function BetaExplainerOpened({ eligible }: { eligible: boolean }) {
  const { record, session, visit } = useBeta();
  const emitted = useRef(false);
  useEffect(() => {
    visit();
    if (!eligible || !session.participating || emitted.current) return;
    emitted.current = true;
    record("explainer_opened");
  }, [eligible, session.participating, record, visit]);
  return null;
}
export function BetaDepthLink({ eligible, children, ...props }: React.AnchorHTMLAttributes<HTMLAnchorElement> & { eligible: boolean }) {
  const { record } = useBeta();
  return <a {...props} onClick={event => { props.onClick?.(event); if (eligible) record("source_opened"); }}>{children}</a>;
}
export function BetaTimeline({ eligible, children }: { eligible: boolean; children: React.ReactNode }) {
  const { record, session } = useBeta();
  const emitted = useRef(false);
  return <details className="editorial-timeline" onToggle={event => {
    if (event.currentTarget.open && eligible && session.participating && !emitted.current) { emitted.current = true; record("timeline_opened"); }
  }}><summary>사건의 흐름 펼쳐보기</summary>{children}</details>;
}
export function BetaForm() {
  const { session, state, source, enroll, withdraw } = useBeta();
  const [email, setEmail] = useState("");
  const [consent, setConsent] = useState(false);
  const [cohort, setCohort] = useState<"friend" | "external">("external");
  const [chosenSource, setChosenSource] = useState<BetaSource | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [failed, setFailed] = useState(false);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!consent || !email.trim() || state !== "available") return;
    setBusy(true); setMessage(""); setFailed(false);
    try { await enroll({ email: email.trim(), consent: true, cohort, source: chosenSource || source }); setEmail(""); }
    catch { setFailed(true); setMessage("신청을 완료하지 못했습니다. 잠시 후 다시 시도해 주세요. 참여 자료는 확인되지 않았습니다."); }
    finally { setBusy(false); }
  }
  async function leave() {
    setBusy(true); setFailed(false); setMessage("");
    try { await withdraw(); setConsent(false); setMessage("연구 참여를 철회하고 연결된 참여 자료를 삭제했습니다."); }
    catch { setFailed(true); setMessage("철회를 완료하지 못했습니다. 현재 참여 상태가 유지됩니다. 잠시 후 다시 시도해 주세요."); }
    finally { setBusy(false); }
  }
  if (session.participating) return <section className="settings-panel beta-form"><h2>베타 연구에 참여 중입니다</h2><p>이 브라우저에서 해설 열람·원문 확인·타임라인 펼치기와 재방문 여부를 확인합니다. 연락처는 연구 안내와 인터뷰 연락에만 사용합니다.</p><Link href="/start" className="button">이슈 읽으러 가기</Link><p>참여는 선택이며, 언제든 연결된 참여 자료를 삭제할 수 있습니다.</p><button className="button secondary" disabled={busy} onClick={() => void leave()}>{busy ? "처리 중…" : "연구 참여 철회 및 자료 삭제"}</button><p role={failed ? "alert" : "status"} className="form-status">{message}</p></section>;
  return <section className="settings-panel beta-form"><MarketingVisit /><h2>더 이해하기 쉬운 서비스를 함께 만들어요</h2><p>신청 없이도 이슈와 원문을 읽을 수 있습니다. 연구에 참여하면 사용 경험을 살펴보고 필요한 경우 짧은 인터뷰를 요청합니다.</p><form onSubmit={submit}>
    <label htmlFor="beta-email">이메일 주소</label><input id="beta-email" type="email" autoComplete="email" required maxLength={254} value={email} onChange={event => setEmail(event.target.value)} />
    <label htmlFor="beta-cohort">운영자와의 관계</label><select id="beta-cohort" value={cohort} onChange={event => setCohort(event.target.value as typeof cohort)}><option value="external">직접 아는 사이가 아니에요</option><option value="friend">지인·기존 네트워크예요</option></select>
    <label htmlFor="beta-source">서비스를 알게 된 경로</label><select id="beta-source" value={chosenSource || source} onChange={event => setChosenSource(event.target.value as BetaSource)}>{BETA_SOURCES.map(item => <option key={item} value={item}>{{ instagram: "인스타그램", network: "지인 초대", community: "제품 소개 커뮤니티", direct: "직접 방문·기타" }[item]}</option>)}</select>
    <div className="beta-consent-info"><strong>참여 자료와 보관 안내</strong><p>이메일은 연구 안내·인터뷰 연락을 위해, 임의의 참여 코드는 첫 읽기와 재방문을 확인하기 위해 사용합니다. 일반 행동 종류·방문일·자발적 방문 또는 연구 요청 방문 여부와 신청 시 선택한 관계·유입 경로를 수집합니다. 개인별 이슈명·인물명·정치 성향은 수집하지 않습니다. 연락처와 행동 기록은 분리하고 신청 후 35일 이내 삭제합니다. 이 브라우저에서 참여를 철회할 수 있습니다.</p></div>
    <label className="beta-checkbox"><input type="checkbox" required checked={consent} onChange={event => setConsent(event.target.checked)} /><span>위 목적의 연락처·사용 기록 수집과 35일 이내 보관에 동의하고 베타 연구에 참여합니다. (선택)</span></label>
    <button className="button" disabled={busy || state !== "available"}>{busy ? "신청 중…" : "베타 연구 참여 신청"}</button>
    {state === "unavailable" ? <p role="alert" className="form-status">참여 신청 서버에 연결할 수 없습니다. 이슈 읽기는 계속 이용할 수 있습니다. 잠시 후 새로고침해 주세요.</p> : <p role={failed ? "alert" : "status"} className="form-status">{state === "loading" ? "참여 상태를 확인하고 있습니다…" : message}</p>}
  </form><Link href="/start" className="text-link">로그인 없이 이슈 읽기</Link><p className="muted">이 브라우저의 참여 쿠키로 상태를 확인합니다. 다른 기기에서는 참여 상태가 자동으로 연결되지 않습니다.</p></section>;
}
