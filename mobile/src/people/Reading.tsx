import type {
  KnowledgeEvidence,
  PublicContext,
} from "../../../web/src/lib/knowledge-contracts";
import type { GraphKind } from "../../../web/src/lib/graph-contracts";
import type { Settings } from "../state";
import { useResource } from "./data";
import { InlinePeople } from "./InlinePeople";
import { SAMPLE_PARAGRAPHS, sampleMentions } from "./preview";
import { Connections } from "./Connections";
import { PublicRefresh } from "./PublicMeta";
import { Icon } from "../components/Icon";
import { safeSource } from "../../../web/src/lib/format";
import { Browser } from "@capacitor/browser";
import { Capacitor } from "@capacitor/core";

export function RecordReading({
  id,
  settings,
  onPerson,
  onEvidence,
}: {
  id: string;
  settings: Settings;
  onPerson: (id: string) => void;
  onEvidence: (id: string) => void;
}) {
  const enabled = settings.mode === "live" || id.startsWith("sample-history-");
  const context = useResource<PublicContext>(
    settings,
    enabled ? `/api/v1/activities/${id}/context` : null,
  );
  if (settings.mode === "preview" && id === "sample-care")
    return (
      <section className="reading-article">
        <p className="person-sample-note">
          인물 연결을 눌러보는 UX 예시예요. 아래 인물과 이야기는 가상입니다.
        </p>
        <h2>기록 속 사람을 만나는 방법</h2>
        {SAMPLE_PARAGRAPHS.map((text, i) => (
          <p key={i} className="reading-paragraph">
            <InlinePeople
              text={text}
              mentions={sampleMentions(text)}
              onPerson={onPerson}
            />
          </p>
        ))}
        <p className="person-coverage">
          이름을 눌러 미리보기를 열고, 인물 문서에서 돌아와 이 문단을 이어 읽어
          보세요.
        </p>
      </section>
    );
  if (!enabled) return null;
  if (context.status === "loading")
    return (
      <p className="loading-state" role="status">
        공개된 인물·문맥 연결을 읽고 있어요.
      </p>
    );
  if (context.status === "error" || context.status === "not-found")
    return (
      <div className="person-empty">
        <p>
          {context.status === "not-found"
            ? "공개된 인물·문맥 자료를 찾지 못했어요."
            : "인물·문맥 연결을 불러오지 못했어요."}
        </p>
        <button className="text-button" onClick={context.reload}>
          문맥 연결 재시도
        </button>
      </div>
    );
  if (!context.data) return null;
  if (!context.data.evidence.length && !context.data.participants.length)
    return (
      <p className="person-empty">현재 공개 범위에 인물·문맥 연결이 없어요.</p>
    );
  return (
    <section className="reading-article">
      <h2>원문에서 함께 읽기</h2>
      {context.data.evidence.map((evidence) => (
        <article key={evidence.id}>
          <p className="reading-paragraph">
            <InlinePeople
              text={evidence.excerpt}
              mentions={evidence.mentions}
              offset={evidence.start}
              onPerson={onPerson}
            />
          </p>
          <button
            className="text-button"
            onClick={() => onEvidence(evidence.id)}
          >
            원문 문맥과 출처 확인
          </button>
        </article>
      ))}
      {context.data.participants.length > 0 && (
        <div className="related-person-chips" aria-label="확인된 참여 인물">
          {context.data.participants.map((person) => (
            <button
              key={`${person.personId}-${person.role}`}
              data-reader-focus={`participant-${person.personId}`}
              onClick={() => onPerson(person.personId)}
            >
              {person.name} <Icon name="arrow" size={14} />
            </button>
          ))}
        </div>
      )}
    </section>
  );
}
export function EvidenceScreen({
  id,
  settings,
  onPerson,
  onBack,
}: {
  id: string;
  settings: Settings;
  onPerson: (id: string) => void;
  onBack: () => void;
}) {
  const data = useResource<KnowledgeEvidence>(
    settings,
    `/api/v1/evidence/${id}`,
  );
  const evidence = data.data,
    source = evidence ? safeSource(evidence.sourceUrl) : null;
  return (
    <>
      <div className="detail-toolbar">
        <button className="icon-button" aria-label="뒤로" onClick={onBack}>
          <Icon name="back" />
        </button>
        <span>원문과 근거</span>
        <PublicRefresh
          settings={settings}
          loading={data.status === "loading"}
          onRefresh={data.reload}
          label="공개 근거 새로고침"
        />
      </div>
      {data.status === "loading" ? (
        <p className="loading-state" role="status">
          근거를 읽고 있어요.
        </p>
      ) : !evidence ? (
        <section className="empty-state">
          <h1>
            {data.status === "not-found"
              ? "공개된 근거가 없어요"
              : "근거를 불러오지 못했어요"}
          </h1>
          <button className="secondary-button" onClick={data.reload}>
            근거 다시 읽기
          </button>
        </section>
      ) : (
        <>
          <div className="detail-heading">
            <h1>{evidence.title}</h1>
          </div>
          {settings.mode === "preview" && (
            <p className="person-sample-note">가상 본문 · UX 예시</p>
          )}
          <section className="reading-article">
            {evidence.before && (
              <p className="evidence-context">{evidence.before}</p>
            )}
            <blockquote className="reading-paragraph">
              <InlinePeople
                text={evidence.excerpt}
                mentions={evidence.mentions}
                offset={evidence.start}
                onPerson={onPerson}
              />
            </blockquote>
            {evidence.after && (
              <p className="evidence-context">{evidence.after}</p>
            )}
          </section>
          {source && (
            <a
              href={source}
              target="_blank"
              rel="noopener noreferrer"
              className="secondary-button wide law-source-link"
              onClick={(event) => {
                if (Capacitor.isNativePlatform()) {
                  event.preventDefault();
                  void Browser.open({ url: source, toolbarColor: "#ffffff" });
                }
              }}
            >
              공식 원문 열기 <Icon name="external" size={17} />
            </a>
          )}
          <details className="wiki-section wiki-fold">
            <summary>출처와 버전 확인</summary>
            <dl className="person-source-details">
              <dt>원문 위치</dt>
              <dd>{evidence.locator || "원문 구간"}</dd>
              <dt>원문 버전</dt>
              <dd>{evidence.documentVersion}</dd>
              <dt>추출 버전</dt>
              <dd>{evidence.extractionVersion}</dd>
            </dl>
          </details>
        </>
      )}
    </>
  );
}
export function GraphScreen({
  id,
  kind,
  settings,
  onBack,
  ...links
}: {
  id: string;
  kind: GraphKind;
  settings: Settings;
  onBack: () => void;
  onPerson: (id: string) => void;
  onActivity: (id: string) => void;
  onEvidence: (id: string) => void;
  onGraph: (kind: GraphKind, id: string) => void;
}) {
  return (
    <>
      <div className="detail-toolbar">
        <button className="icon-button" aria-label="뒤로" onClick={onBack}>
          <Icon name="back" />
        </button>
        <span>이어지는 기록</span>
      </div>
      <div className="screen-title">
        <h1>근거를 따라 연결해요.</h1>
        <p>선택한 기록에서 확인된 다음 연결이에요.</p>
      </div>
      <Connections id={id} kind={kind} settings={settings} {...links} />
    </>
  );
}
