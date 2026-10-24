import type { Metadata } from "next";
import { UnsubscribeNotifications } from "@/components/auth";
export const metadata: Metadata = { title: "이메일 알림 중단", robots: { index: false, follow: false }, referrer: "no-referrer" };
export default function UnsubscribePage() { return <UnsubscribeNotifications />; }
