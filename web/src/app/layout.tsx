import type { Metadata } from "next";
import Link from "next/link";
import { InterestsProvider } from "@/components/interests";
import { BetaProvider } from "@/components/beta";
import "./globals.css";
export const metadata: Metadata = {
  title: { default: "의정의 흐름 · 정부활동 추적", template: "%s | 의정의 흐름" },
  description: "관심 인물과 이슈의 새로운 변화를 공식 기록과 근거로 확인하세요.",
  robots: { index: true, follow: true }
};
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return <html lang="ko"><body><InterestsProvider><BetaProvider>
    <a className="skip-link" href="#main">본문으로 바로가기</a>
    <header className="site-header"><div className="header-inner"><Link className="brand" href="/" aria-label="의정의 흐름 홈"><span className="brand-symbol" aria-hidden="true">◎</span><span>의정의 흐름<small>공개 기록에서 이어지는 변화</small></span></Link><nav aria-label="주 메뉴"><Link href="/">변화 피드</Link><Link href="/start">처음 오셨나요</Link><Link href="/issues">이슈</Link><Link href="/people">인물</Link><Link href="/bills">법안</Link><Link href="/search">검색</Link><Link href="/interests" className="nav-interests">내 관심</Link></nav></div></header>
    <main id="main" className="page-container">{children}</main>
    <footer className="site-footer"><div><strong>의정의 흐름</strong><p>정치에 관심 있는 사람이, 변화를 직접 확인할 수 있도록.</p></div><nav aria-label="서비스 안내"><Link href="/coverage">자료 범위</Link><Link href="/about">편집·정정 원칙</Link><Link href="/beta">베타 연구 참여</Link><Link href="/research">서비스 검증·구독</Link></nav><p className="footer-note">공식 발표는 해당 기관의 발표 기록입니다. 의결·법령 시행·정책 효과는 구분해서 확인합니다.</p></footer>
  </BetaProvider></InterestsProvider></body></html>;
}
