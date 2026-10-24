import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { getPerson, getPersonProfile } from "@/lib/server-api";
import { FollowButton } from "@/components/interests";
import { ActivityList } from "@/components/activity-list";
import { ApiNotice } from "@/components/api-notice";
import { PersonProfileDetails, PersonActivities, KnowledgeUnavailable } from "@/components/knowledge-panels";
import { GraphExploreLink } from "@/components/knowledge-graph";
export const dynamic = "force-dynamic";
type Props = { params: Promise<{ id: string }> };
export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const id = (await params).id;
  const [result, profile] = await Promise.all([getPerson(id), getPersonProfile(id)]);
  const name = profile.status === "ok" ? profile.data.name : result.status === "ok" ? result.data.name : null;
  return name ? { title: `${name} 활동 기록`, description: `${name}의 법안·표결·발표를 공식 기록에서 확인하세요.` } : { title: "인물 기록", robots: { index: false } };
}
export default async function PersonPage({ params }: Props) {
  const id = (await params).id;
  const [result, profile] = await Promise.all([getPerson(id), getPersonProfile(id)]);
  if (result.status === "not-found" && profile.status === "not-found") notFound();
  if (result.status !== "ok" && profile.status !== "ok") return <ApiNotice status="offline" />;
  const person = profile.status === "ok" ? profile.data : result.status === "ok" ? result.data : null;
  if (!person) return null;
  const legacy = result.status === "ok" ? result.data : null;
  const legacyActivities = legacy?.activities?.filter(activity => profile.status !== "ok" || !profile.data.activities.some(context => context.eventId === activity.id));
  return <><div className="breadcrumbs"><Link href="/people">인물</Link> / {person.name}</div>
    <header className="detail-header"><p className="eyebrow">인물 기록</p><div className="detail-title-row"><h1>{person.name}</h1><FollowButton kind="person" targetId={person.id} label={person.name} /></div>
      {profile.status !== "ok" && <p className="detail-summary">{[legacy?.organization, legacy?.role].filter(Boolean).join(" · ") || "직위 정보 확인 중"}</p>}
      <p className="muted">동명이인은 이름만으로 합치지 않습니다. 각 활동에는 당시 직위·소속과 확인 근거를 연결합니다.</p>
      <GraphExploreLink kind="person" id={person.id} />
    </header><KnowledgeUnavailable status={profile.status} />
    {profile.status === "ok" && <PersonProfileDetails profile={profile.data} />}
    <div className="section-heading"><h2>확인된 활동</h2><Link className="text-link" href={`/?personId=${encodeURIComponent(person.id)}`}>전체 활동 피드 →</Link></div>
    {profile.status === "ok" ? <PersonActivities personId={person.id} contexts={profile.data.activities} /> : <ActivityList activities={legacyActivities} />}
    {profile.status === "ok" && Boolean(legacyActivities?.length) && <section className="detail-section"><h2>추가 공개 기록</h2><p className="muted">세부 역할과 문서 연결을 아직 제공하지 않는 공개 기록입니다.</p><ActivityList activities={legacyActivities} /></section>}
  </>;
}
