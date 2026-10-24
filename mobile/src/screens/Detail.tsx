import { useEffect, useState } from "react";
import { Browser } from "@capacitor/browser";
import { Capacitor } from "@capacitor/core";
import type { Activity, Evidence } from "../../../web/src/lib/contracts";
import {
  dateLabel,
  safeSource,
  STAGES,
  TYPES,
  VOTE_RESULTS,
} from "../../../web/src/lib/format";
import { readRecords } from "../api";
import type { Settings } from "../state";
import { isEntityId } from "../../../web/src/lib/knowledge-validation";
import { Icon } from "../components/Icon";
import { ReadingIndex } from "../components/ReadingIndex";
import { SourceSheet } from "../components/SourceSheet";
import { RecordReading } from "../people/Reading";
import { sampleRecord } from "../people/preview";
import { beginReadingLoad } from "../navigation";
export function DetailScreen({
  id,
  settings,
  onBack,
  onSave,
  onPerson,
  onEvidence,
  onBill,
}: {
  id: string;
  settings: Settings;
  onBack: () => void;
  onSave: (id: string) => void;
  onPerson: (id: string) => void;
  onEvidence: (id: string) => void;
  onBill: (id: string) => void;
}) {
  const [record, setRecord] = useState<Activity | null>(null);
  const [status, setStatus] = useState("loading");
  const [revision, setRevision] = useState(0);
  const [sourceError, setSourceError] = useState("");
  const [selectedSource, setSelectedSource] = useState<{
    evidence: Evidence;
    number: number;
  } | null>(null);
  useEffect(() => {
    let active = true;
    const settled = beginReadingLoad();
    setRecord(null);
    setStatus("loading");
    void (async () => {
      if (settings.mode === "preview") {
        const sample = sampleRecord(id);
        if (active) {
          setRecord(sample || null);
          setStatus(sample ? "ok" : "not-found");
        }
        return;
      }
      const result = await readRecords<Activity>(
        settings.origin,
        `/api/v1/activities/${encodeURIComponent(id)}`,
      );
      if (active) {
        setStatus(result.status);
        if (result.status === "ok") setRecord(result.data);
      }
    })().finally(settled);
    return () => {
      active = false;
      settled();
    };
  }, [id, settings.mode, settings.origin, revision]);
  const openSource = async (value: string) => {
    const url = safeSource(value);
    if (!url) return;
    try {
      if (Capacitor.isNativePlatform())
        await Browser.open({ url, toolbarColor: "#ffffff" });
      else window.open(url, "_blank", "noopener,noreferrer");
    } catch {
      setSourceError("원문을 열지 못했어요. 다시 시도해 주세요.");
    }
  };
  const preview = settings.mode === "preview";
  const saved = settings.saved[settings.mode].includes(id);
  return (
    <>
      <div className="detail-toolbar">
        <button className="icon-button" aria-label="뒤로" onClick={onBack}>
          <Icon name="back" />
        </button>
        <span>기록과 근거</span>
        {record && (
          <button
            className={`detail-save-button ${saved ? "is-saved" : ""}`}
            aria-label={saved ? "저장 해제" : "저장"}
            aria-pressed={saved}
            onClick={() => onSave(id)}
          >
            <Icon name="bookmark" filled={saved} size={18} />
            <span>{saved ? "저장 해제" : "저장"}</span>
          </button>
        )}
      </div>
      {status === "loading" ? (
        <div className="loading-state" role="status">
          기록을 읽고 있어요.
        </div>
      ) : !record ? (
        <div className="empty-state">
          <Icon name="refresh" size={32} />
          <h1>
            {status === "not-found"
              ? "공개된 기록을 찾지 못했어요"
              : "기록을 불러오지 못했어요"}
          </h1>
          <p>연결 상태와 자료 공개 여부를 확인해 주세요.</p>
          <button
            className="secondary-button"
            onClick={() => setRevision((n) => n + 1)}
          >
            다시 불러오기
          </button>
        </div>
      ) : (
        <>
          <section className="detail-heading">
            <div className="detail-tags">
              <span className="type-label">
                {TYPES[record.type] || "공개 기록"}
              </span>
              <span className="stage">
                {STAGES[record.stage] || "단계 미확인"}
              </span>
              {!preview && (
                <time
                  className="detail-date"
                  dateTime={record.occurredAt || record.publishedAt}
                >
                  {record.occurredAt ? "발생" : "공개"}{" "}
                  {dateLabel(record.occurredAt || record.publishedAt)}
                </time>
              )}
              {record.corrected && (
                <span className="correction-label">정정된 기록</span>
              )}
            </div>
            <h1 id="note-summary" tabIndex={-1}>
              {record.title}
            </h1>
            <p>
              {record.summary ||
                "요약이 준비되지 않았어요. 원문을 확인해 주세요."}
            </p>
          </section>
          {isEntityId(record.billId) && (
            <button
              className="secondary-button wide"
              data-reader-focus={`activity-bill-${record.billId}`}
              onClick={() => onBill(record.billId!)}
            >
              연결된 법안과 원안·대안 보기 <Icon name="arrow" size={17} />
            </button>
          )}
          <div className="note-layout">
            <ReadingIndex
              items={[
                ["note-summary", "요약"],
                ["note-context", "맥락"],
                ["note-evidence", "근거"],
                ["note-coverage", "자료 범위"],
              ]}
            />
            <article className="note-body" aria-label="기록 읽기">
              <h2
                id="note-context"
                tabIndex={-1}
                className="note-section-heading"
              >
                기록의 맥락
              </h2>
              <section className="meaning-note">
                <Icon name="shield" size={20} />
                <p>
                  {preview
                    ? "디자인 설명용 예시예요. 실제 정부 활동과 공식 근거를 나타내지 않아요."
                    : record.type === "announcement"
                      ? "기관이 발표한 계획·주장에 관한 기록이에요. 실제 시행과 정책 효과는 별도로 확인해야 해요."
                      : "표시된 단계는 이 기록의 상태예요. 정책 전체의 성과나 특정 인물의 공로를 의미하지 않아요."}
                </p>
              </section>
              <RecordReading
                id={id}
                settings={settings}
                onPerson={onPerson}
                onEvidence={onEvidence}
              />
              <section className="detail-section">
                <div className="section-title">
                  <h2 id="note-evidence" tabIndex={-1}>
                    공식 근거
                  </h2>
                  <span>{record.evidence.length}개</span>
                </div>
                {preview ? (
                  <div className="evidence-empty">
                    <Icon name="shield" />
                    <p>
                      실제 기록에서는 원문 발췌,
                      <br />
                      문서 위치와 버전을 여기서 확인해요.
                    </p>
                  </div>
                ) : record.evidence.length ? (
                  record.evidence.map((e, index) => (
                    <article className="evidence-item" key={e.id}>
                      {e.excerpt && <blockquote>{e.excerpt}</blockquote>}
                      <button
                        className="text-button source-detail-trigger"
                        aria-label={`근거 ${index + 1} 자세히 보기`}
                        onClick={() =>
                          setSelectedSource({ evidence: e, number: index + 1 })
                        }
                      >
                        근거 {index + 1} · 위치와 버전{" "}
                        <Icon name="arrow" size={15} />
                      </button>
                    </article>
                  ))
                ) : (
                  <p className="secondary-text">
                    공개된 발췌가 없어요. 원문과 자료 범위를 확인해 주세요.
                  </p>
                )}
                {!preview &&
                  safeSource(record.sourceUrl) &&
                  !record.evidence.some(
                    (e) =>
                      safeSource(e.sourceUrl) === safeSource(record.sourceUrl),
                  ) && (
                    <button
                      className="secondary-button wide"
                      onClick={() => void openSource(record.sourceUrl)}
                    >
                      출처에서 직접 확인하기 <Icon name="external" size={17} />
                    </button>
                  )}
                <p role="status" className="form-message">
                  {sourceError}
                </p>
              </section>
              {!preview && (
                <section className="detail-section">
                  <h2>기록의 시간</h2>
                  <dl className="date-list">
                    <div>
                      <dt>실제 발생</dt>
                      <dd>{dateLabel(record.occurredAt)}</dd>
                    </div>
                    <div>
                      <dt>원문 공개</dt>
                      <dd>{dateLabel(record.publishedAt)}</dd>
                    </div>
                    <div>
                      <dt>수집</dt>
                      <dd>{dateLabel(record.collectedAt)}</dd>
                    </div>
                    {record.changedAt && (
                      <div>
                        <dt>변화 공개</dt>
                        <dd>{dateLabel(record.changedAt)}</dd>
                      </div>
                    )}
                    <div>
                      <dt>공개 버전</dt>
                      <dd>{record.version}</dd>
                    </div>
                  </dl>
                </section>
              )}
              {!!record.votes.length && (
                <section className="detail-section">
                  <h2>공개된 표결</h2>
                  <p className="secondary-text">
                    확인되지 않은 개인별 기록을 불참으로 추정하지 않아요.
                  </p>
                  {record.votes.map((vote, i) => (
                    <div
                      className="vote-row"
                      key={`${vote.sessionId}-${vote.personId}-${i}`}
                    >
                      <strong>{vote.name}</strong>
                      <span>
                        {VOTE_RESULTS[vote.result] || "개인별 기록 미확인"}
                      </span>
                    </div>
                  ))}
                </section>
              )}
              <section className="detail-section coverage-section">
                <h2 id="note-coverage" tabIndex={-1}>
                  자료 범위
                </h2>
                <p>{record.coverage || "자료 범위를 확인하고 있어요."}</p>
              </section>
            </article>
          </div>
        </>
      )}
      {selectedSource && (
        <SourceSheet
          {...selectedSource}
          onClose={() => setSelectedSource(null)}
        />
      )}
    </>
  );
}
