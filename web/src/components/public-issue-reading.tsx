"use client";
import { useEffect, useLayoutEffect, useRef, useState, useTransition } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import type { IssueReading, IssueReadingBlock, IssueReadingResult } from "@/lib/issue-reading";
import { ISSUE_READING_MESSAGES } from "@/lib/issue-reading-messages";
import { dateLabel } from "@/lib/format";

const LABELS = { background: "어떤 일인가요?", fact: "확인된 내용", claim: "당사자의 입장·주장", unknown: "아직 확인하지 못한 부분", event: "시간순 경과" };
type Position = { version: string; anchor: string | null; section: string | null; offset: number; focus: string | null; expanded: boolean };
type Entry = { issueId: string; id: string };
function readingEntry(id: string, known: Entry | null): Entry {
  let entry = known?.issueId === id ? known : history.state?.issueReadingEntry;
  if (!entry || entry.issueId !== id) {
    entry = { issueId: id, id: crypto.randomUUID() };
  }
  // Next refresh replaces its history state. Retain our identity across that refresh.
  history.replaceState({ ...history.state, issueReadingEntry: entry }, "");
  return entry;
}
function savedPosition(key: string): Position | null {
  try { return JSON.parse(sessionStorage.getItem(key) || "null") as Position | null; } catch { return null; }
}
function EvidenceLinks({ ids, prefix }: { ids: string[]; prefix: string }) {
  return <span className="knowledge-links">{ids.map((id, index) => <Link key={id} className="source-link" data-reader-focus={`${prefix}-${id}`} href={`/evidence/${id}`}>근거 {index + 1} →</Link>)}</span>;
}
function Section({ kind, reading }: { kind: IssueReadingBlock["kind"]; reading: IssueReading }) {
  const blocks = reading.blocks.filter(b => b.kind === kind);
  if (!blocks.length) return null;
  return <section className="detail-section" data-reader-section={`issue-section-${kind}`}><h2>{LABELS[kind]}</h2>
    {kind === "claim" && <p className="muted">당사자의 입장이며 공식 판단이나 실제 이행과 구분합니다.</p>}
    {blocks.map(block => <div className="editorial-source" key={block.id} data-reader-anchor={`block-${block.id}`}>
      {block.date && <time dateTime={block.date}>{dateLabel(block.date)}</time>}{block.title && <h3>{block.title}</h3>}
      <p>{block.text}</p><EvidenceLinks ids={block.evidenceIds} prefix={`block-${block.id}`} />
      {block.personIds.map(id => <Link key={id} className="text-link" data-reader-focus={`person-${block.id}-${id}`} href={`/people/${id}`}>관련 인물 · {reading.people.find(p => p.id === id)!.name} →</Link>)}
    </div>)}
  </section>;
}
export function PublicIssueReading({ result, id }: { result: IssueReadingResult; id: string }) {
  const router = useRouter();
  const root = useRef<HTMLDivElement>(null);
  const key = useRef("");
  const entry = useRef<Entry | null>(null);
  const revalidated = useRef(false);
  const [expanded, setExpanded] = useState(false);
  const [priorVersion, setPriorVersion] = useState("");
  const [pending, startTransition] = useTransition();
  const reading = result.status === "ok" ? result.data : null;
  const remember = (trigger?: HTMLElement) => {
    if (!root.current || !reading || !key.current) return;
    const active = trigger || (document.activeElement instanceof HTMLElement ? document.activeElement : null);
    const anchors = Array.from(root.current.querySelectorAll<HTMLElement>("[data-reader-anchor]"));
    const anchor = active?.closest<HTMLElement>("[data-reader-anchor]") || anchors.find(el => {
      const r = el.getBoundingClientRect(); return el.getClientRects().length > 0 && r.bottom > 0 && r.top < innerHeight;
    });
    const value: Position = { version: reading.version, anchor: anchor?.dataset.readerAnchor || null,
      section: anchor?.closest<HTMLElement>("[data-reader-section]")?.dataset.readerSection || null,
      offset: anchor ? -anchor.getBoundingClientRect().top : 0, focus: active?.dataset.readerFocus || null, expanded };
    try { sessionStorage.setItem(key.current, JSON.stringify(value)); } catch { /* Reading does not require storage. */ }
  };
  useLayoutEffect(() => {
    entry.current = readingEntry(id, entry.current);
    key.current = `parliament:issue-reading:${entry.current.id}`;
    const position = savedPosition(key.current);
    if (!position || pending) return;
    setExpanded(Boolean(position.expanded));
    setPriorVersion(position.version);
    if (!revalidated.current) {
      revalidated.current = true;
      startTransition(() => router.refresh());
      return;
    }
    let frame = requestAnimationFrame(() => { frame = requestAnimationFrame(() => {
      if (!root.current) return;
      const anchors = Array.from(root.current.querySelectorAll<HTMLElement>("[data-reader-anchor]"));
      const anchor = anchors.find(el => el.dataset.readerAnchor === position.anchor && el.getClientRects().length > 0);
      const fallback = Array.from(root.current.querySelectorAll<HTMLElement>("[data-reader-section]")).find(el => el.dataset.readerSection === position.section) || anchors[0];
      const target = anchor || fallback;
      if (target) window.scrollTo({ top: Math.max(0, window.scrollY + target.getBoundingClientRect().top + (anchor && Number.isFinite(position.offset) ? position.offset : 0)), behavior: "instant" });
      const focus = Array.from(root.current.querySelectorAll<HTMLElement>("[data-reader-focus]")).find(el => el.dataset.readerFocus === position.focus && el.getClientRects().length > 0);
      (focus || root.current.querySelector<HTMLElement>("h1"))?.focus({ preventScroll: true });
    }); });
    return () => cancelAnimationFrame(frame);
  }, [id, reading?.version, result.status, pending]);
  useEffect(() => {
    const save = () => remember();
    window.addEventListener("pagehide", save);
    return () => window.removeEventListener("pagehide", save);
  }, [reading?.version, expanded]);
  const refresh = () => { remember(); revalidated.current = true; startTransition(() => router.refresh()); };
  return <div ref={root} onClickCapture={event => {
    const target = event.target instanceof Element ? event.target.closest<HTMLElement>("[data-reader-focus]") : null;
    if (target) remember(target);
  }}>
    <div className="section-heading"><Link className="text-link" href="/issues">이슈 목록 →</Link><button className="button secondary" data-reader-focus="reading-refresh" disabled={pending} onClick={refresh}>공개 해설 새로고침</button></div>
    {pending ? <p role="status">공개 해설을 다시 확인하고 있어요.</p> : !reading ? <section className="empty-state" role="status"><h1 tabIndex={-1}>{ISSUE_READING_MESSAGES[result.status as keyof typeof ISSUE_READING_MESSAGES].title}</h1><p>{ISSUE_READING_MESSAGES[result.status as keyof typeof ISSUE_READING_MESSAGES].description}</p></section>
      : <article className="editorial-article" data-reading-version={reading.version}>
        <header className="editorial-header" data-reader-anchor="reading-top"><p className="eyebrow">사람 검토 후 공개된 해설</p><h1 tabIndex={-1}>{reading.title}</h1><p className="detail-summary">{reading.summary}</p><EvidenceLinks ids={reading.summaryEvidenceIds} prefix="summary" /><p className="muted">마지막 원문 확인 · {dateLabel(reading.checkedAt)}</p></header>
        {priorVersion && priorVersion !== reading.version && <p role="status" className="notice">새 공개 버전을 확인했어요.</p>}
        <section className="detail-section" data-reader-anchor="reading-stage"><h2>지금 어느 단계인가요?</h2><p>{reading.currentStage}</p><EvidenceLinks ids={reading.stageEvidenceIds} prefix="stage" /><h3>다음에 확인할 지점</h3><p>{reading.nextTrigger}</p></section>
        <Section kind="background" reading={reading} />
        <details className="detail-section" open={expanded} onToggle={event => setExpanded(event.currentTarget.open)}><summary>경과와 쟁점 더 읽기</summary>{(["event", "fact", "claim", "unknown"] as const).map(kind => <Section key={kind} kind={kind} reading={reading} />)}</details>
        <section className="detail-section"><h2>자료 범위와 공개 정보</h2><p>{reading.coverage || "공개 범위 설명이 제공되지 않았어요."}</p><p className="muted">공개 검토 · {new Intl.DateTimeFormat("ko-KR", { timeZone: "Asia/Seoul", dateStyle: "short", timeStyle: "short" }).format(new Date(reading.reviewedAt))}</p><details><summary>공개 버전 확인</summary><p style={{ overflowWrap: "anywhere" }}>{reading.version}</p></details><h3>확인·변경 이력</h3>{reading.updates.length ? <ul>{reading.updates.map((u, index) => <li key={index}>{dateLabel(u.date)} · {u.note}</li>)}</ul> : <p className="muted">공개된 변경 이력이 없어요.</p>}</section>
      </article>}
  </div>;
}
