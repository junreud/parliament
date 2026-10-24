import type { Metadata } from "next";
import { BetaForm } from "@/components/beta";
export const metadata: Metadata = { title: "베타 연구 참여", robots: { index: false, follow: true } };
export default function BetaPage() {
  return <div className="beta-page"><header className="detail-header"><p className="eyebrow">의정의 흐름 · 베타 연구</p><h1>뉴스를 이해하는 데<br />도움이 되었나요?</h1><p className="detail-summary">정치 뉴스를 접했지만 맥락이 궁금했던 분을 찾습니다. 평소 정치에 얼마나 관심 있는지는 상관없습니다.</p></header><BetaForm /></div>;
}
