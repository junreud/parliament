import type { Activity } from "../../../web/src/lib/contracts";
import { STAGES, TOPICS, TYPES, dateLabel } from "../../../web/src/lib/format";
import { Icon } from "./Icon";
export function RecordCard({
  record,
  preview,
  saved,
  onSave,
  onOpen,
}: {
  record: Activity;
  preview: boolean;
  saved: boolean;
  onSave: () => void;
  onOpen: () => void;
}) {
  const topic = record.topics.find((id) => Object.hasOwn(TOPICS, id));
  return (
    <article className="record-card">
      <div className="record-top">
        <div>
          <span className="record-kind">
            {TYPES[record.type] || "공개 기록"}
          </span>
          <span className="record-date">
            {preview
              ? "화면 구성 예시"
              : `${record.occurredAt ? "발생" : "공개"} ${dateLabel(record.occurredAt || record.publishedAt)}`}
          </span>
        </div>
        <button
          className={`save-button ${saved ? "is-saved" : ""}`}
          aria-label={saved ? "저장 해제" : "저장"}
          aria-pressed={saved}
          onClick={onSave}
        >
          <Icon name="bookmark" filled={saved} size={18} />
          <span>{saved ? "저장 해제" : "저장"}</span>
        </button>
      </div>
      <h3>{record.title}</h3>
      <p className="record-summary">
        {record.summary ||
          "요약이 준비되지 않았어요. 공식 원문에서 확인해 주세요."}
      </p>
      <div className="record-bottom">
        <span className={`stage stage-${record.stage}`}>
          현재 단계 · {STAGES[record.stage] || "미확인"}
        </span>
        {topic && <span className="topic-label">{TOPICS[topic]}</span>}
        {record.corrected && <span className="correction-label">정정</span>}
      </div>
      <button
        className="record-open"
        aria-label={`${record.title} 기록 읽기`}
        onClick={onOpen}
      >
        <span>기록 읽기</span>
        <Icon name="arrow" size={18} />
      </button>
    </article>
  );
}
