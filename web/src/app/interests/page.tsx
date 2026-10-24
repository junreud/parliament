import type { Metadata } from "next";
import { InterestsSettings } from "@/components/interests";
import { LoginForm } from "@/components/auth";
export const metadata: Metadata = { title: "내 관심과 알림", robots: { index: false } };
export default function InterestsPage() {
  return <><div className="detail-header"><p className="eyebrow">My interests</p><h1>관심 있는 대상의 다음 변화</h1><p className="muted">인물·법안·이슈를 등록하고 최신 기록을 함께 확인하세요.</p></div><InterestsSettings /><LoginForm /></>;
}
