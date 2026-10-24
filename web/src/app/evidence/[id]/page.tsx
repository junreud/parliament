import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { getEvidence } from "@/lib/server-api";
import { ApiNotice } from "@/components/api-notice";
import { EvidenceView } from "@/components/knowledge-evidence";

export const dynamic = "force-dynamic";
type Props = { params: Promise<{ id: string }> };
export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const result = await getEvidence((await params).id);
  return result.status === "ok" ? { title: `${result.data.title} · 원문 근거`, description: "고정된 원문 버전의 발췌와 앞뒤 문맥." } : { title: "원문 근거", robots: { index: false } };
}
export default async function EvidencePage({ params }: Props) {
  const result = await getEvidence((await params).id);
  if (result.status === "not-found") notFound();
  if (result.status !== "ok") return <ApiNotice status={result.status} />;
  return <><div className="breadcrumbs"><Link href="/">변화 피드</Link> / 원문 근거</div><header className="detail-header"><p className="eyebrow">원문과 문맥</p><h1>{result.data.title}</h1><p className="muted">이 근거는 원문·추출 버전과 구간을 고정합니다. 발췌와 앞뒤 문맥을 함께 확인하세요.</p></header><div className="detail-section"><EvidenceView evidence={result.data} /></div></>;
}
