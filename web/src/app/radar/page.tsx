import type { Metadata } from "next";
import { readApi } from "@/lib/api";
import type { RadarPage } from "@/lib/radar";
import { NewsRadar } from "@/components/news-radar";
import { ApiNotice } from "@/components/api-notice";
export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "지금, 무슨 이슈?" };
export default async function Radar() {
  const result = await readApi<RadarPage>("/api/v1/radar");
  return (
    <>
      <p className="eyebrow">뉴스에서 시작하는 맥락</p>
      <h1>지금, 무슨 이슈?</h1>
      <p className="muted">흘려본 제목에서, 확인할 원문까지.</p>
      {result.status === "ok" ? (
        <NewsRadar page={result.data} />
      ) : (
        <ApiNotice status={result.status} />
      )}
    </>
  );
}
