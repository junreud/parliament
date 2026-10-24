import type { Metadata } from "next";
import { VerifyLogin } from "@/components/auth";
export const metadata: Metadata = { title: "이메일 로그인 확인", robots: { index: false, follow: false }, referrer: "no-referrer" };
export default function VerifyPage() { return <VerifyLogin />; }
