import { useLayoutEffect, useRef, useState } from "react";
import type {
  PersonProfile,
  PublicContext,
} from "../../../web/src/lib/knowledge-contracts";
import type { GraphKind } from "../../../web/src/lib/graph-contracts";
import { dateLabel, TYPES } from "../../../web/src/lib/format";
import type { Settings } from "../state";
import { useReadingView } from "../navigation";
import { usePages, useResource } from "./data";
import { Connections } from "./Connections";
import { Icon } from "../components/Icon";
import { OfficeDates, EvidenceLinks, PublicRefresh } from "./PublicMeta";
import { motionReduced } from "../motion";

export const ROLES: Record<string, string> = {
  lead_sponsor: "대표발의",
  co_sponsor: "공동발의",
  speaker: "발언",
  voter: "표결 참여",
  scheduled_participant: "참여 예정",
};
type View = {
  tab: "overview" | "activity" | "connections";
  order: "newest" | "oldest";
  role: string;
  from: string;
  until: string;
  pages: number;
  positions: Record<string, number>;
};
const INITIAL: View = {
  tab: "overview",
  order: "newest",
  role: "",
  from: "",
  until: "",
  pages: 1,
  positions: { overview: 0, activity: 0, connections: 0 },
};
const monthFormatter = new Intl.DateTimeFormat("en-CA", {
  timeZone: "Asia/Seoul",
  year: "numeric",
  month: "2-digit",
});
function monthParts(date: string) {
  const parts = monthFormatter.formatToParts(new Date(date));
  return {
    year: parts.find((part) => part.type === "year")!.value,
    month: parts.find((part) => part.type === "month")!.value,
  };
}
type Props = {
  id: string;
  entryId: string;
  settings: Settings;
  onBack: () => void;
  onPerson: (id: string) => void;
  onActivity: (id: string) => void;
  onEvidence: (id: string) => void;
  onGraph: (kind: GraphKind, id: string) => void;
};

function Overview({
  profile,
  onView,
  onActivity,
  onEvidence,
  onGraph,
}: {
  profile: PersonProfile;
  onView: (view: Partial<View>) => void;
  onActivity: (id: string) => void;
  onEvidence: (id: string) => void;
  onGraph: (kind: GraphKind, id: string) => void;
}) {
  const sections = [
    ["person-intro", "소개"],
    ["person-tenures", "직위·소속 이력"],
    ["person-bills", "법안·입법활동"],
    ["person-votes", "공개 표결"],
    ["person-speech", "발언·발표"],
    ["person-topics", "주제별 활동"],
    ["person-sources", "출처·자료 범위"],
  ];
  const classifications = [
    {
      id: "person-bills",
      title: "법안·입법활동",
      types: ["bill"],
      role: "lead_sponsor",
      action: "대표발의 기록 보기",
    },
    {
      id: "person-votes",
      title: "공개 표결",
      types: ["vote"],
      role: "voter",
      action: "표결 기록 보기",
    },
    {
      id: "person-speech",
      title: "발언·발표",
      types: ["speech", "announcement"],
      role: "speaker",
      action: "발언 기록 보기",
    },
  ];
  return (
    <>
      <label className="wiki-index">
        문서 목차
        <select
          aria-label="인물 문서 목차"
          defaultValue="person-intro"
          onChange={(event) =>
            document.getElementById(event.target.value)?.scrollIntoView({
              block: "start",
              behavior: motionReduced() ? "instant" : "smooth",
            })
          }
        >
          {sections.map(([id, label]) => (
            <option value={id} key={id}>
              {label}
            </option>
          ))}
        </select>
      </label>
      <section className="wiki-section" id="person-intro">
        <h2>소개</h2>
        {profile.facts.length ? (
          profile.facts.map((fact, i) => (
            <div className="person-fact" key={`${fact.label}-${i}`}>
              <strong>{fact.label}</strong>
              <p>
                {(
                  {
                    source_current_roster: "원천의 현재 명부에서 확인",
                    source_profile: "기관 소개에서 확인",
                    source_dated_office_statement:
                      "발표 당시 직위 · 현재 재임 미확인",
                    source_local_candidate: "출처별 신원 검토 대상",
                    unknown: "미확인",
                    unresolved: "다른 출처와의 신원 연결 미확인",
                  } as Record<string, string>
                )[fact.value] || fact.value}
              </p>
              <EvidenceLinks
                ids={fact.evidenceIds}
                onEvidence={onEvidence}
                focusKey={`fact-${i}`}
              />
            </div>
          ))
        ) : (
          <p className="secondary-text">
            공개 근거가 있는 소개를 아직 확보하지 못했어요.
          </p>
        )}
      </section>
      <section className="wiki-section" id="person-tenures">
        <h2>직위·소속 이력</h2>
        {profile.tenures.length ? (
          <ol className="tenure-list">
            {profile.tenures.map((tenure, i) => (
              <li key={`${tenure.organizationId}-${i}`}>
                <strong>{tenure.position}</strong>
                <p>
                  {tenure.organizationName || "기관명 확인 중"}
                  {tenure.party ? ` · ${tenure.party}` : ""}
                </p>
                <OfficeDates
                  observedAt={tenure.observedAt}
                  validFrom={tenure.validFrom}
                  validUntil={tenure.validUntil}
                />
                <EvidenceLinks
                  focusKey={`tenure-${i}`}
                  ids={tenure.evidenceIds}
                  onEvidence={onEvidence}
                />
              </li>
            ))}
          </ol>
        ) : (
          <p className="secondary-text">
            확인된 직위 이력이 아직 없어요. 기록이 없다는 뜻은 아니에요.
          </p>
        )}
      </section>
      {classifications.map((section) => {
        const contexts = profile.activities.filter((context) =>
          section.types.includes(context.activity.type),
        );
        return (
          <details
            className="wiki-section wiki-fold"
            key={section.id}
            id={section.id}
          >
            <summary>
              {section.title}
              <span>
                {contexts.length
                  ? `최근 연결 ${contexts.length}건`
                  : "자료 범위 확인"}
              </span>
            </summary>
            <div>
              {contexts.slice(0, 3).map((context) => (
                <button
                  className="wiki-record-link"
                  key={context.eventId}
                  onClick={() => onActivity(context.eventId)}
                >
                  {context.activity.title}
                  <Icon name="arrow" size={16} />
                </button>
              ))}
              <p className="secondary-text">
                {contexts.length
                  ? "최근 프로필에 연결된 자료이며 전체 이력은 아니에요."
                  : "이 항목의 자료를 아직 충분히 확보하지 못했어요."}
              </p>
              <button
                className="text-button"
                onClick={() =>
                  onView({ tab: "activity", role: section.role, pages: 1 })
                }
              >
                {section.action}
              </button>
            </div>
          </details>
        );
      })}
      <section className="wiki-section" id="person-topics">
        <h2>주제별 활동</h2>
        {profile.relatedIssues.length ? (
          profile.relatedIssues.map((issue) => (
            <button
              className="wiki-record-link"
              key={issue.id}
              onClick={() => onGraph("issue", issue.id)}
            >
              {issue.title}
              <Icon name="arrow" size={16} />
            </button>
          ))
        ) : (
          <p className="secondary-text">
            근거가 있는 이슈 연결을 아직 확보하지 못했어요.
          </p>
        )}
      </section>
      <section className="wiki-section person-coverage" id="person-sources">
        <h2>출처·자료 범위</h2>
        <p>
          공개 검수를 통과한 자료만 연결해요. 명부·소개와 과거 활동의 수집
          범위는 달라요. 단순 언급을 수행 활동으로 집계하지 않으며 자료가 없다는
          이유로 불참이나 무활동을 추정하지 않아요.
        </p>
        <p>
          원문 근거는 각 항목에서 확인할 수 있어요. 활동 탭에서는 최근 프로필
          목록의 범위를 넘어 과거 기록을 이어서 읽어요.
        </p>
      </section>
    </>
  );
}
function Timeline({
  id,
  settings,
  view,
  onView,
  onActivity,
  onEvidence,
}: {
  id: string;
  settings: Settings;
  view: View;
  onView: (view: Partial<View>) => void;
  onActivity: (id: string) => void;
  onEvidence: (id: string) => void;
}) {
  const [from, setFrom] = useState(view.from),
    [until, setUntil] = useState(view.until),
    [message, setMessage] = useState("");
  const query = new URLSearchParams({
    limit: "20",
    order: view.order,
    ...(view.role ? { role: view.role } : {}),
    ...(view.from ? { from: view.from } : {}),
    ...(view.until ? { until: view.until } : {}),
  });
  const data = usePages<PublicContext>(
    settings,
    `/api/v1/people/${id}/timeline?${query}`,
    view.pages,
  );
  return (
    <>
      <PublicRefresh
        settings={settings}
        loading={data.status === "loading"}
        onRefresh={data.reload}
        label="공개 활동 새로고침"
      />
      <div className="person-activity-filters">
        <label>
          활동 정렬
          <select
            aria-label="활동 정렬"
            value={view.order}
            onChange={(event) =>
              onView({ order: event.target.value as View["order"], pages: 1 })
            }
          >
            <option value="newest">최근순</option>
            <option value="oldest">과거순</option>
          </select>
        </label>
        <label>
          활동 역할
          <select
            aria-label="활동 역할"
            value={view.role}
            onChange={(event) => onView({ role: event.target.value, pages: 1 })}
          >
            <option value="">확인된 모든 역할</option>
            {Object.entries(ROLES).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
      </div>
      <form
        className="person-period"
        onSubmit={(event) => {
          event.preventDefault();
          if (from && until && from > until) {
            setMessage("시작일이 종료일보다 늦어요.");
            return;
          }
          setMessage("");
          onView({ from, until, pages: 1 });
        }}
      >
        <label>
          시작일
          <input
            type="date"
            aria-label="시작일"
            value={from}
            onChange={(event) => setFrom(event.target.value)}
          />
        </label>
        <label>
          종료일
          <input
            type="date"
            aria-label="종료일"
            value={until}
            onChange={(event) => setUntil(event.target.value)}
          />
        </label>
        <button className="secondary-button">기간 적용</button>
      </form>
      {message && (
        <p className="form-message" role="status">
          {message}
        </p>
      )}
      {(view.from || view.until || view.role) && (
        <button
          className="text-button"
          onClick={() => {
            setFrom("");
            setUntil("");
            onView({ from: "", until: "", role: "", pages: 1 });
          }}
        >
          기간·역할 초기화
        </button>
      )}
      <p className="person-section-intro">
        발생일을 우선 표시하고, 발생일이 없으면 공개일 기준임을 표시해요. 각
        카드의 역할은 해당 기록에서 확인된 내용이에요.
      </p>
      {data.status === "loading" ? (
        <p className="loading-state" role="status">
          시간순 기록을 읽고 있어요.
        </p>
      ) : data.status !== "ok" ? (
        <section className="person-empty">
          <p role="alert">
            {data.partial
              ? "일부 활동 기록을 불러오지 못했어요"
              : data.status === "not-found"
                ? "공개된 활동 목록을 찾지 못했어요"
                : "활동 기록을 불러오지 못했어요"}
          </p>
          {data.partial && (
            <p>
              확인한 앞 페이지는 아래에 유지했어요. 다음 페이지를 다시 확인해
              주세요.
            </p>
          )}
          <button className="text-button" onClick={data.reload}>
            활동 재시도
          </button>
        </section>
      ) : !data.items.length ? (
        <section className="person-empty">
          <h2>선택한 조건에서 확인된 기록이 없어요</h2>
          <p>
            수집하지 못한 활동이 있을 수 있어요. 기간이나 역할을 바꿔 보세요.
          </p>
        </section>
      ) : null}
      <ol className="person-timeline">
        {data.items.map((context, index) => {
          const activity = context.activity,
            date = activity.occurredAt || activity.publishedAt;
          const previous = data.items[index - 1],
            previousDate =
              previous &&
              (previous.activity.occurredAt || previous.activity.publishedAt);
          const month = monthParts(date),
            previousMonth = previousDate ? monthParts(previousDate) : null;
          const labels = [
            ...new Set([
              ...context.participants
                .filter((p) => p.personId === id)
                .map((p) => ROLES[p.role] || "역할 미확인"),
              TYPES[activity.type] || "공개 기록",
            ]),
          ];
          return (
            <li key={`${context.eventId}:${context.eventVersion}`}>
              {`${month.year}-${month.month}` !==
                `${previousMonth?.year}-${previousMonth?.month}` && (
                <h2 className="timeline-month">
                  {month.year}
                  <span>{month.month}월</span>
                </h2>
              )}
              <article className="person-activity">
                <div className="person-activity-meta">
                  <time dateTime={date}>{dateLabel(date)}</time>
                  <span>{activity.occurredAt ? "발생일" : "공개일 기준"}</span>
                </div>
                <div className="person-role-chips">
                  {labels.map((label) => (
                    <span key={label}>{label}</span>
                  ))}
                  {activity.corrected && <span>정정된 기록</span>}
                </div>
                <button
                  className="person-activity-open"
                  data-reader-focus={`timeline-${context.eventId}`}
                  onClick={() => onActivity(context.eventId)}
                >
                  <h3>{activity.title}</h3>
                  <Icon name="arrow" size={17} />
                </button>
                {activity.summary && <p>{activity.summary}</p>}
                {activity.stage === "scheduled" && (
                  <p className="person-sample-note">
                    참여 예정 기록이며 실제 진행 결과는 별도로 확인해요.
                  </p>
                )}
                {context.evidence[0] && (
                  <button
                    className="text-button"
                    onClick={() => onEvidence(context.evidence[0].id)}
                  >
                    이 기록의 근거
                  </button>
                )}
              </article>
            </li>
          );
        })}
      </ol>
      {data.nextCursor && data.status === "ok" && (
        <button
          className="secondary-button wide"
          onClick={() => onView({ pages: view.pages + 1 })}
        >
          이전 기록 더 보기 <Icon name="arrow" size={17} />
        </button>
      )}
      <p className="person-coverage">
        현재 조건에서 {data.items.length}건을 읽었어요. 전체 활동 수를 뜻하지
        않아요.
      </p>
    </>
  );
}
export function PersonScreen(props: Props) {
  const { id, entryId, settings, onBack, ...links } = props;
  const profile = useResource<PersonProfile>(
    settings,
    `/api/v1/people/${id}/profile`,
  );
  const [view, setView] = useReadingView<View>(`person:${entryId}`, INITIAL);
  const restoreTab = useRef<number | null>(null);
  const update = (patch: Partial<View>) => {
    if (patch.tab && patch.tab !== view.tab)
      restoreTab.current = view.positions[patch.tab] || 0;
    setView({
      ...view,
      ...patch,
      positions: { ...view.positions, [view.tab]: window.scrollY },
    });
  };
  useLayoutEffect(() => {
    if (restoreTab.current === null) return;
    const y = restoreTab.current;
    let complete = false;
    const restore = () => {
      if (
        complete ||
        document.documentElement.scrollHeight - innerHeight + 2 < y
      )
        return;
      window.scrollTo({ top: y, behavior: "instant" });
      complete = true;
      restoreTab.current = null;
      observer.disconnect();
    };
    const observer = new ResizeObserver(restore);
    observer.observe(document.getElementById("main-content")!);
    restore();
    return () => observer.disconnect();
  }, [view.tab]);
  return (
    <>
      <div className="detail-toolbar">
        <button className="icon-button" aria-label="뒤로" onClick={onBack}>
          <Icon name="back" />
        </button>
        <span>인물 문서</span>
        <PublicRefresh
          settings={settings}
          loading={profile.status === "loading"}
          onRefresh={profile.reload}
          label="공개 문서 새로고침"
        />
      </div>
      {profile.status === "loading" ? (
        <p role="status" className="loading-state">
          인물 문서를 읽고 있어요.
        </p>
      ) : !profile.data ? (
        <section className="empty-state">
          <h1>
            {profile.status === "not-found"
              ? "공개된 인물 문서가 없어요"
              : "인물 자료를 불러오지 못했어요"}
          </h1>
          <p>연결 실패와 자료 미공개는 활동이 없다는 뜻이 아니에요.</p>
          <button className="secondary-button" onClick={profile.reload}>
            인물 다시 읽기
          </button>
        </section>
      ) : (
        <>
          <header className="person-profile-header">
            <div className="person-identity">
              <span className="person-avatar large">
                {profile.data.name.slice(0, 1)}
              </span>
              <div>
                <h1>{profile.data.name}</h1>
                <p>
                  {profile.data.tenures[0]?.organizationName
                    ? `기록된 소속 · ${profile.data.tenures[0].organizationName}`
                    : "소속 확인 중"}
                </p>
                {profile.data.tenures[0] ? (
                  <OfficeDates {...profile.data.tenures[0]} />
                ) : (
                  <small>직위 정보는 근거 확인 후 표시해요.</small>
                )}
              </div>
            </div>
            {settings.mode === "preview" && (
              <p className="person-sample-note">
                가상 인물 · UX 예시예요. 실제 공직자·정치 활동이 아니에요.
              </p>
            )}
          </header>
          <div
            className="person-tabs"
            role="tablist"
            aria-label="인물 문서 보기"
          >
            {(
              [
                ["overview", "개요"],
                ["activity", "활동"],
                ["connections", "연결"],
              ] as const
            ).map(([tab, label]) => (
              <button
                role="tab"
                key={tab}
                id={`person-tab-${tab}`}
                aria-controls="person-panel"
                aria-selected={view.tab === tab}
                tabIndex={view.tab === tab ? 0 : -1}
                onClick={() => update({ tab })}
                onKeyDown={(event) => {
                  const tabs = ["overview", "activity", "connections"] as const;
                  const current = tabs.indexOf(tab);
                  const index =
                    event.key === "Home"
                      ? 0
                      : event.key === "End"
                        ? 2
                        : event.key === "ArrowRight"
                          ? (current + 1) % tabs.length
                          : event.key === "ArrowLeft"
                            ? (current + tabs.length - 1) % tabs.length
                            : -1;
                  if (index < 0) return;
                  event.preventDefault();
                  update({ tab: tabs[index] });
                  document
                    .getElementById(`person-tab-${tabs[index]}`)
                    ?.focus({ preventScroll: true });
                }}
              >
                {label}
              </button>
            ))}
          </div>
          <div
            id="person-panel"
            role="tabpanel"
            aria-labelledby={`person-tab-${view.tab}`}
          >
            {view.tab === "overview" ? (
              <Overview profile={profile.data} onView={update} {...links} />
            ) : view.tab === "activity" ? (
              <Timeline
                key={profile.revision}
                id={id}
                settings={settings}
                view={view}
                onView={update}
                {...links}
              />
            ) : (
              <Connections
                key={profile.revision}
                id={id}
                settings={settings}
                {...links}
              />
            )}
          </div>
        </>
      )}
    </>
  );
}
