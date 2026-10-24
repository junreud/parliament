"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { REPRESENTATIVE_ISSUE_ID, type IssueReadingResult } from "@/lib/issue-reading";
import { readBrowserIssueReading } from "@/lib/issue-reading-browser";
import { ISSUE_READING_MESSAGES } from "@/lib/issue-reading-messages";

export function ReviewedIssueEntry() {
  const [result, setResult] = useState<IssueReadingResult | null>(null);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    let active = true;
    setResult(null);
    void readBrowserIssueReading(REPRESENTATIVE_ISSUE_ID).then(value => { if (active) setResult(value); });
    return () => { active = false; };
  }, [revision]);
  return <section className="detail-section" aria-label="편집자 선정 해설"><p className="eyebrow">편집자 선정 · 화제 순위와 별도</p><h2>배경부터 깊이 읽기</h2>
    {!result ? <p role="status">공개된 선정 해설을 확인하고 있어요.</p> : result.status === "ok" ? <Link className="marketing-issue-card" href={`/issues/${result.data.issueId}`}><h3>{result.data.title}</h3><p>{result.data.summary}</p><span className="text-link">사람 검토 후 공개 · 쉬운 해설 읽기 →</span></Link> : <>
      <p role="status">{result.status === "not-found" ? "현재 공개된 선정 해설이 없어요." : ISSUE_READING_MESSAGES[result.status].title}</p><button className="button secondary" onClick={() => setRevision(value => value + 1)}>선정 해설 다시 확인</button>
    </>}
  </section>;
}
