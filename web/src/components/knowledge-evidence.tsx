import type { ReactNode } from "react";
import Link from "next/link";
import type { KnowledgeEvidence, Mention } from "@/lib/knowledge-contracts";
import { isEntityId } from "@/lib/knowledge-validation";
import { safeSource } from "@/lib/format";

export function MentionText({ text, mentions, offset = 0 }: { text: string; mentions: Mention[]; offset?: number }) {
  const points = Array.from(text);
  const ranges = mentions.filter(mention => mention.start >= offset && mention.end <= offset + points.length)
    .sort((a, b) => a.start - b.start || a.end - b.end);
  const invalid = ranges.some((mention, index) =>
    !Number.isSafeInteger(mention.start) || !Number.isSafeInteger(mention.end) || mention.end <= mention.start ||
    (index > 0 && mention.start < ranges[index - 1].end) ||
    points.slice(mention.start - offset, mention.end - offset).join("") !== mention.surface);
  if (invalid) return <span className="source-text">{text}</span>;
  const parts: ReactNode[] = [];
  let cursor = 0;
  for (const mention of ranges) {
    if (mention.decision !== "approved" || !isEntityId(mention.personId)) continue;
    const start = mention.start - offset;
    const end = mention.end - offset;
    parts.push(points.slice(cursor, start).join(""));
    parts.push(<Link key={mention.id} className="person-mention" href={`/people/${encodeURIComponent(mention.personId)}`}>{mention.surface}</Link>);
    cursor = end;
  }
  parts.push(points.slice(cursor).join(""));
  return <span className="source-text">{parts}</span>;
}
export function EvidenceView({ evidence }: { evidence: KnowledgeEvidence }) {
  const source = safeSource(evidence.sourceUrl);
  return <section className="evidence-block" aria-label="고정된 원문 근거">
    <p><span className="badge">원문 발췌</span> {evidence.title}</p>
    {evidence.before && <p className="source-text evidence-context"><span className="context-label">앞 문맥</span>{evidence.before}</p>}
    <blockquote><MentionText text={evidence.excerpt} mentions={evidence.mentions} offset={evidence.start} /></blockquote>
    {evidence.after && <p className="source-text evidence-context"><span className="context-label">뒤 문맥</span>{evidence.after}</p>}
    <p className="evidence-meta">{evidence.locator || "원문 구간"} · 원문 버전: {evidence.documentVersion} · 추출 버전: {evidence.extractionVersion}</p>
    <div className="knowledge-links"><Link className="text-link" href={`/documents/${encodeURIComponent(evidence.documentId)}?${new URLSearchParams({ version: evidence.documentVersion, extractionVersion: evidence.extractionVersion })}`}>이 버전의 문서 보기 →</Link>{source && <a className="source-link" href={source} target="_blank" rel="noreferrer">공식 원문 확인 ↗</a>}</div>
  </section>;
}

export function EvidenceLinks({ ids }: { ids: string[] }) {
  return <span className="knowledge-links">{ids.filter(isEntityId).map((id, index) => <Link className="source-link" key={id} href={`/evidence/${encodeURIComponent(id)}`}>근거 {index + 1} →</Link>)}</span>;
}
