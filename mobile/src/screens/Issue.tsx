import { useEffect } from "react";
import type {
  IssueReading,
  IssueReadingBlock,
} from "../../../web/src/lib/issue-reading";
import { ISSUE_READING_MESSAGES } from "../../../web/src/lib/issue-reading-messages";
import { dateLabel } from "../../../web/src/lib/format";
import type { Settings } from "../state";
import { useIssueReading } from "../useIssueReading";
import { useEntryView } from "../navigation";
import { EvidenceLinks } from "../people/PublicMeta";
import { Icon } from "../components/Icon";

const SECTIONS = {
  background: "어떤 일인가요?",
  fact: "확인된 내용",
  claim: "당사자의 입장·주장",
  unknown: "아직 확인하지 못한 부분",
  event: "시간순 경과",
} as const;
type Props = {
  id: string;
  settings: Settings;
  onBack: () => void;
  onPerson: (id: string) => void;
  onEvidence: (id: string) => void;
  onSettings: () => void;
  onPrepareReload: () => void;
};
function Section({
  kind,
  reading,
  onPerson,
  onEvidence,
}: {
  kind: IssueReadingBlock["kind"];
  reading: IssueReading;
  onPerson: Props["onPerson"];
  onEvidence: Props["onEvidence"];
}) {
  const blocks = reading.blocks.filter((block) => block.kind === kind);
  if (!blocks.length) return null;
  return (
    <section
      className="wiki-section"
      data-reader-section={`issue-section-${kind}`}
    >
      <h2>{SECTIONS[kind]}</h2>
      {kind === "claim" && (
        <p className="secondary-text">
          당사자의 입장이며 공식 판단이나 실제 이행과 구분해 읽어요.
        </p>
      )}
      {blocks.map((block) => (
        <article
          className="issue-block"
          data-reader-anchor={`block-${block.id}`}
          key={block.id}
        >
          {block.date && (
            <time dateTime={block.date}>{dateLabel(block.date)}</time>
          )}
          {block.title && <h3>{block.title}</h3>}
          <p className="reading-paragraph">{block.text}</p>
          <EvidenceLinks
            ids={block.evidenceIds}
            onEvidence={onEvidence}
            label="문단 근거"
            focusKey={`issue-${reading.issueId}-${block.id}`}
          />
          {block.personIds.length > 0 && (
            <div
              className="related-person-chips"
              aria-label="이 문단의 승인된 관련 인물"
            >
              {block.personIds.map((id) => {
                const person = reading.people.find((p) => p.id === id)!;
                return (
                  <button
                    key={id}
                    data-reader-focus={`issue-person-${block.id}-${id}`}
                    aria-label={`관련 인물 ${person.name} 미리보기`}
                    onClick={() => onPerson(id)}
                  >
                    관련 인물 · {person.name} <Icon name="arrow" size={14} />
                  </button>
                );
              })}
            </div>
          )}
        </article>
      ))}
    </section>
  );
}
export function IssueScreen({
  id,
  settings,
  onBack,
  onPerson,
  onEvidence,
  onSettings,
  onPrepareReload,
}: Props) {
  const { result, reload } = useIssueReading(settings, id);
  const [expanded, setExpanded] = useEntryView(`issue:${id}:more`, false);
  const [seenVersion, setSeenVersion] = useEntryView(
    `issue:${id}:seen-version`,
    "",
  );
  const reading = result.status === "ok" ? result.data : null;
  useEffect(() => {
    if (reading && !seenVersion) setSeenVersion(reading.version);
  }, [reading?.version, seenVersion]);
  const refresh = () => {
    onPrepareReload();
    reload();
  };
  const sections = reading ? { reading, onPerson, onEvidence } : null;
  return (
    <>
      <div className="detail-toolbar">
        <button className="icon-button" aria-label="뒤로" onClick={onBack}>
          <Icon name="back" />
        </button>
        <span>이슈 해설</span>
        {settings.mode === "live" && (
          <button
            className="text-button public-refresh"
            data-reader-focus="issue-refresh"
            disabled={result.status === "loading"}
            onClick={refresh}
          >
            공개 해설 새로고침
          </button>
        )}
      </div>
      {result.status === "loading" ? (
        <p className="loading-state" role="status">
          공개 해설을 읽고 있어요.
        </p>
      ) : result.status === "unconfigured" ? (
        <section className="empty-state">
          <h1>공개 기록 모드에서 해설을 읽을 수 있어요</h1>
          <p>설정에서 공개 서버에 연결해 주세요.</p>
          <button className="secondary-button" onClick={onSettings}>
            연결 설정 보기
          </button>
        </section>
      ) : !reading ? (
        <section className="empty-state" role="status">
          <h1 tabIndex={-1} data-reading-fallback>
            {
              ISSUE_READING_MESSAGES[
                result.status as keyof typeof ISSUE_READING_MESSAGES
              ].title
            }
          </h1>
          <p>
            {
              ISSUE_READING_MESSAGES[
                result.status as keyof typeof ISSUE_READING_MESSAGES
              ].description
            }
          </p>
          <button className="secondary-button" onClick={refresh}>
            해설 다시 읽기
          </button>
        </section>
      ) : (
        <article
          className="issue-reading"
          data-reading-version={reading.version}
        >
          <header className="detail-heading" data-reader-anchor="reading-top">
            <p className="eyebrow">사람 검토 후 공개된 해설</p>
            <h1 tabIndex={-1} data-reading-fallback>
              {reading.title}
            </h1>
            <p className="reading-paragraph">{reading.summary}</p>
            <EvidenceLinks
              ids={reading.summaryEvidenceIds}
              onEvidence={onEvidence}
              label="요약 근거"
              focusKey={`issue-${id}-summary`}
            />
            <p className="secondary-text">
              마지막 원문 확인 · {dateLabel(reading.checkedAt)}
            </p>
          </header>
          {seenVersion && seenVersion !== reading.version && (
            <p className="person-sample-note" role="status">
              새 공개 버전을 확인했어요.
            </p>
          )}
          <section className="wiki-section" data-reader-anchor="reading-stage">
            <h2>지금 어느 단계인가요?</h2>
            <p className="reading-paragraph">{reading.currentStage}</p>
            <EvidenceLinks
              ids={reading.stageEvidenceIds}
              onEvidence={onEvidence}
              label="현재 단계 근거"
              focusKey={`issue-${id}-stage`}
            />
            <h3>다음에 확인할 지점</h3>
            <p className="secondary-text">{reading.nextTrigger}</p>
          </section>
          <Section kind="background" {...sections!} />
          <details
            className="wiki-section wiki-fold issue-more"
            open={expanded}
            onToggle={(event) => setExpanded(event.currentTarget.open)}
          >
            <summary>경과와 쟁점 더 읽기</summary>
            <div>
              {(["event", "fact", "claim", "unknown"] as const).map((kind) => (
                <Section key={kind} kind={kind} {...sections!} />
              ))}
            </div>
          </details>
          <section className="wiki-section">
            <h2>자료 범위와 공개 정보</h2>
            <p className="secondary-text">
              {reading.coverage || "공개 범위 설명이 제공되지 않았어요."}
            </p>
            <dl className="person-source-details">
              <dt>공개 검토 시각</dt>
              <dd>
                {new Intl.DateTimeFormat("ko-KR", {
                  timeZone: "Asia/Seoul",
                  dateStyle: "short",
                  timeStyle: "short",
                }).format(new Date(reading.reviewedAt))}
              </dd>
              <dt>공개 버전</dt>
              <dd>{reading.version}</dd>
            </dl>
            <h3>확인·변경 이력</h3>
            {reading.updates.length ? (
              <ul>
                {reading.updates.map((u, index) => (
                  <li key={`${u.date}-${index}`}>
                    {dateLabel(u.date)} · {u.note}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="secondary-text">공개된 변경 이력이 없어요.</p>
            )}
          </section>
        </article>
      )}
    </>
  );
}
