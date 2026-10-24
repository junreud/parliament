import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { getDocument } from "@/lib/server-api";
import { ApiNotice } from "@/components/api-notice";
import { MentionText } from "@/components/knowledge-evidence";
import { dateLabel, safeSource } from "@/lib/format";

export const dynamic = "force-dynamic";
type Props = { params: Promise<{ id: string }>; searchParams: Promise<{ version?: string; extractionVersion?: string }> };
const BODY_STATUS: Record<string, string> = { available: "본문 확보", partial: "본문 일부 확보", unavailable: "본문 미확보", disclaimer_only: "안내문만 확보", unsupported: "추출 미지원 형식", failed: "본문 추출 실패" };

export async function generateMetadata({ params, searchParams }: Props): Promise<Metadata> {
  const query = await searchParams;
  const result = await getDocument((await params).id, query.version, query.extractionVersion);
  return result.status === "ok" ? { title: result.data.title, description: "공식 문서의 확인된 원문 구간과 인물 연결." } : { title: "공식 문서", robots: { index: false } };
}

export default async function DocumentPage({ params, searchParams }: Props) {
  const query = await searchParams;
  const result = await getDocument((await params).id, query.version, query.extractionVersion);
  if (result.status === "not-found") notFound();
  if (result.status !== "ok") return <ApiNotice status={result.status} />;
  const document = result.data;
  const source = safeSource(document.sourceUrl);
  return <><div className="breadcrumbs"><Link href="/">변화 피드</Link> / 공식 문서</div>
    <header className="detail-header"><p className="eyebrow">공식 문서</p><h1>{document.title}</h1><p className="muted">공식 원문에서 확인한 텍스트입니다. 인물 연결은 신원이 확인된 이름에만 제공합니다.</p>
      <div className="tag-row"><span className="badge">{BODY_STATUS[document.bodyStatus] || "자료 상태 미확인"}</span><span className="stage">{document.format.toUpperCase()}</span></div>
      {source && <a className="source-link" href={source} target="_blank" rel="noreferrer">공식 원문 확인 ↗</a>}
    </header><section className="detail-section"><h2>문서 버전과 자료 상태</h2><dl className="dates-list"><dt>원문 공개일</dt><dd>{dateLabel(document.publishedAt)}{document.datePrecision === "date" && " · 날짜 단위"}</dd><dt>수집일</dt><dd>{dateLabel(document.collectedAt)}</dd><dt>원문 버전</dt><dd>{document.version}</dd><dt>추출 버전</dt><dd>{document.extractionVersion}</dd><dt>이용 조건</dt><dd>{document.licenseStatus === "allowed" ? "확인된 이용 조건에 따라 제공" : document.licenseStatus === "restricted" ? "본문 재이용 제한" : "본문 재이용 조건 미확인"}</dd></dl>
      <p><Link className="source-link" href={`/documents/${encodeURIComponent(document.id)}?${new URLSearchParams({ version: document.version, extractionVersion: document.extractionVersion })}`}>이 버전의 문서 링크 →</Link></p>
    </section><section className="detail-section"><h2>확인된 원문 구간</h2>{document.segments.length ? document.segments.map(segment => <section className="document-segment" key={segment.id} id={`segment-${segment.id}`}><h3>{segment.locator}</h3><p><MentionText text={segment.text} mentions={segment.mentions} /></p></section>) : <p className="notice">공개할 본문 구간이 없습니다. 자료 상태와 공식 원문을 확인해 주세요.</p>}</section>
  </>;
}
