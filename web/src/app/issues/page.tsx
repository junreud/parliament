import type { Metadata } from "next";
import Link from "next/link";
import { readApi } from "@/lib/api";
import type { Issue, Page } from "@/lib/contracts";
import { TOPICS } from "@/lib/format";
import { ApiNotice } from "@/components/api-notice";
export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "이슈의 흐름" };
export default async function IssuesPage() {
  const result = await readApi<Page<Issue>>("/api/v1/issues");
  return <><p className="eyebrow">Issues</p><h1>이슈의 흐름을 한곳에서</h1><Link href="/radar" className="text-link">뉴스에서 발견한 현재 이슈 →</Link><p className="muted">발표에서 법안·표결·후속 조치까지. 검토된 사건 연결을 중심으로 읽습니다.</p>{result.status === "ok" && result.data.items.length ? <div className="browser-grid">{result.data.items.map(issue => <Link className="browser-card" href={`/issues/${encodeURIComponent(issue.id)}`} key={issue.id}><span className="badge">{TOPICS[issue.topic] || issue.topic}</span><h2>{issue.title}</h2><p>{issue.description}</p><span className="text-link">이슈의 변화 보기 →</span></Link>)}</div> : <ApiNotice status={result.status === "ok" ? "empty" : result.status} />}</>;
}
