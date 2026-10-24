import { REPRESENTATIVE_ISSUE_ID } from "../../../web/src/lib/issue-reading";
import { ISSUE_READING_MESSAGES } from "../../../web/src/lib/issue-reading-messages";
import { useIssueReading } from "../useIssueReading";
import type { Settings } from "../state";
import { Icon } from "./Icon";

export function ReviewedIssueEntry({
  settings,
  onOpen,
}: {
  settings: Settings;
  onOpen: (id: string) => void;
}) {
  const { result, reload } = useIssueReading(settings, REPRESENTATIVE_ISSUE_ID);
  if (result.status === "unconfigured") return null;
  return (
    <section className="reviewed-issue-entry" aria-label="편집자 선정 해설">
      <p className="eyebrow">편집자 선정 · 화제 순위와 별도</p>
      <h2>배경부터 깊이 읽기</h2>
      {result.status === "loading" ? (
        <p role="status">공개된 선정 해설을 확인하고 있어요.</p>
      ) : result.status === "ok" ? (
        <button
          className="person-card"
          data-reader-focus={`editorial-${result.data.issueId}`}
          onClick={() => onOpen(result.data.issueId)}
        >
          <span>
            <strong>{result.data.title}</strong>
            <small>사람 검토 후 공개 · 쉬운 해설 읽기</small>
          </span>
          <Icon name="arrow" size={18} />
        </button>
      ) : (
        <>
          <p className="secondary-text" role="status">
            {result.status === "not-found"
              ? "현재 공개된 선정 해설이 없어요."
              : ISSUE_READING_MESSAGES[result.status].title}
          </p>
          <button className="text-button" onClick={reload}>
            선정 해설 다시 확인
          </button>
        </>
      )}
    </section>
  );
}
