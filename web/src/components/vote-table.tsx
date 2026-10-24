import Link from "next/link";
import type { Vote } from "@/lib/contracts";
import { VOTE_RESULTS } from "@/lib/format";
export function VoteTable({ votes }: { votes: Vote[] }) {
  if (!votes.length) return <p className="notice">개인별 표결 기록이 없습니다. 자료 미공개·무기명 표결·미수집 여부는 해당 기록의 자료 범위를 확인해 주세요.</p>;
  return <div className="table-scroll"><table><caption>공개된 개인별 표결 기록</caption><thead><tr><th scope="col">인물</th><th scope="col">표결회차</th><th scope="col">기록</th></tr></thead><tbody>{votes.map((vote, index) => <tr key={`${vote.sessionId}-${vote.personId}-${index}`}><th scope="row"><Link href={`/people/${encodeURIComponent(vote.personId)}`}>{vote.name}</Link></th><td>{vote.sessionId}</td><td>{VOTE_RESULTS[vote.result] || "개인별 기록 미확인"}</td></tr>)}</tbody></table></div>;
}
