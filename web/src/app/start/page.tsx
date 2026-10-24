import type { Metadata } from "next";
import { MarketingStart } from "@/components/marketing-start";
import { getVisibleEditorialIssues, editorialPreviewEnabled } from "@/lib/editorial-data";
import { isReviewedEditorial } from "@/lib/editorial";
export const dynamic = "force-dynamic";
export function generateMetadata(): Metadata {
  const issues = getVisibleEditorialIssues();
  return {
    title: "나라의 근황에서 이어 읽기",
    description: issues.length > 0 ? "흘려본 정치 뉴스, 맥락부터 근거까지. 사건의 배경과 현재 단계, 공식 원문과 다음 확인 지점을 읽어보세요." : "첫 해설을 준비하고 있습니다. 원문과 맥락을 검토한 이슈부터 공개합니다.",
    robots: { index: !editorialPreviewEnabled() && issues.length >= 3 && issues.every(isReviewedEditorial), follow: true }
  };
}
export default function StartPage() { return <MarketingStart issues={getVisibleEditorialIssues()} />; }
