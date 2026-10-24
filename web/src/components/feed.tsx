"use client";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import type { Activity, ApiResult, Page } from "@/lib/contracts";
import { loadFollowFeed } from "@/lib/feed";
import { ActivityCard } from "./activity-card";
import { ApiNotice } from "./api-notice";
import { useInterests } from "./interests";
export function ActivityFeed({ initial, nextHref, filtered }: { initial: ApiResult<Page<Activity>>; nextHref?: string; filtered: boolean }) {
  const { follows, loading } = useInterests();
  const selectedManually = useRef(false);
  const [tab, setTab] = useState<"latest" | "mine">("latest");
  const [mine, setMine] = useState<Awaited<ReturnType<typeof loadFollowFeed>> | null>(null);
  const [fetching, setFetching] = useState(false);
  useEffect(() => {
    if (!loading && !filtered && follows.length && !selectedManually.current) setTab("mine");
  }, [loading, filtered, follows]);
  useEffect(() => {
    if (tab !== "mine" || loading || !follows.length) return;
    let active = true;
    setFetching(true);
    void loadFollowFeed(follows).then(result => { if (active) { setMine(result); setFetching(false); } });
    return () => { active = false; };
  }, [tab, loading, follows]);
  const mineSelected = tab === "mine";
  const records = mineSelected ? mine?.items || [] : initial.status === "ok" ? initial.data.items : [];
  return <section aria-label="활동 변화 피드"><div className="feed-tabs"><button aria-pressed={!mineSelected} onClick={() => { selectedManually.current = true; setTab("latest"); }}>{filtered ? "조건에 맞는 변화" : "최신 변화"}</button><button aria-pressed={mineSelected} onClick={() => { selectedManually.current = true; setTab("mine"); }}>내 관심{follows.length ? ` · ${follows.length}` : ""}</button></div>
    {mineSelected && !follows.length ? <div className="empty-state"><h2>관심 있는 인물과 이슈를 골라보세요</h2><p>관심 대상의 법안·표결·발표를 한곳에서 확인할 수 있습니다.</p><Link className="button" href="/interests">관심 목록 설정</Link></div> : fetching ? <p className="loading-line" role="status"><span className="loading-dot" />관심 대상의 기록을 확인하고 있습니다…</p> : <>
      {mineSelected && <p className="muted">각 관심 대상의 최근 20건을 묶었습니다. 이전 기록은 인물·법안·이슈 페이지에서 확인할 수 있습니다.</p>}
      {mineSelected && mine?.status === "partial" && <p className="notice" role="status">일부 관심 대상의 기록을 불러오지 못했습니다. 표시된 기록이 전체 변화는 아닙니다.</p>}
      {records.length ? <div className="activity-list">{records.map(activity => <ActivityCard key={activity.id} activity={activity} />)}</div> : <ApiNotice status={mineSelected ? mine?.status === "offline" ? "offline" : "empty" : initial.status === "ok" ? "empty" : initial.status} />}
      {!mineSelected && nextHref && <div className="pagination"><Link className="button secondary" href={nextHref}>이전 변화 더 보기</Link></div>}
    </>}
  </section>;
}
