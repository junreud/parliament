"use client";
import { useEffect, useRef, useState } from "react";
import type { Activity } from "@/lib/contracts";
import { matchesFollows } from "@/lib/preferences";
import { useInterests } from "./interests";
export function ActivityFeedback({ activity }: { activity: Pick<Activity, "personIds" | "topics" | "billId"> }) {
  const { authenticated, loading, follows, emitUsage } = useInterests();
  const opened = useRef(false);
  const [rated, setRated] = useState(false);
  useEffect(() => {
    if (!authenticated || loading || opened.current || !follows.length) return;
    if (matchesFollows(activity, follows)) {
      opened.current = true;
      void emitUsage("activity_opened");
      return;
    }
  }, [authenticated, loading, follows, emitUsage, activity]);
  if (!authenticated || loading) return null;
  return <section className="detail-section"><h2>이 내용이 관련 있고 이해하기 쉬웠나요?</h2><p className="muted">서비스 개선을 위한 집계에만 사용합니다. 읽은 인물·이슈 정보는 이 평가에 포함하지 않습니다.</p>{rated ? <p role="status" className="muted">평가에 참여해 주셔서 감사합니다.</p> : <div className="tag-row"><button className="button secondary" onClick={() => { setRated(true); void emitUsage("relevance", true); }}>도움이 되었어요</button><button className="button secondary" onClick={() => { setRated(true); void emitUsage("relevance", false); }}>이해하기 어려웠어요</button></div>}</section>;
}
