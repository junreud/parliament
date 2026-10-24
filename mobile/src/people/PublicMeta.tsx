import { dateLabel } from "../../../web/src/lib/format";
import type { Settings } from "../state";
import { useEntryView } from "../navigation";

export function OfficeDates({
  observedAt,
  validFrom,
  validUntil,
}: {
  observedAt: string | null;
  validFrom?: string | null;
  validUntil?: string | null;
}) {
  return (
    <div className="office-dates">
      <small>
        자료 관측일 · {observedAt ? dateLabel(observedAt) : "미확인"}
      </small>
      <small>
        효력 기간 ·{" "}
        {validFrom === undefined && validUntil === undefined
          ? "공개 목록에 미제공"
          : `${validFrom ? dateLabel(validFrom) : "시작일 미확인"} ~ ${validUntil ? dateLabel(validUntil) : "종료일 미확인"}`}
      </small>
    </div>
  );
}
export function EvidenceLinks({
  ids,
  onEvidence,
  label = "근거",
  focusKey = label,
}: {
  ids: string[];
  onEvidence: (id: string) => void;
  label?: string;
  focusKey?: string;
}) {
  const unique = [...new Set(ids)];
  const [expanded, setExpanded] = useEntryView(`evidence:${focusKey}`, false);
  const button = (id: string, index: number) => (
    <button
      key={id}
      className="text-button person-fact-evidence"
      aria-label={`${label} ${index + 1}`}
      data-reader-focus={`${focusKey}-${id}`}
      onClick={() => onEvidence(id)}
    >
      {label} {index + 1}
    </button>
  );
  return (
    <div className="public-evidence-links">
      {unique.slice(0, 3).map(button)}
      {unique.length > 3 && (
        <details
          open={expanded}
          onToggle={(event) => setExpanded(event.currentTarget.open)}
        >
          <summary>근거 {unique.length - 3}개 더 보기</summary>
          {unique.slice(3).map((id, i) => button(id, i + 3))}
        </details>
      )}
    </div>
  );
}
export function PublicRefresh({
  settings,
  loading,
  onRefresh,
  label,
}: {
  settings: Settings;
  loading: boolean;
  onRefresh: () => void;
  label: string;
}) {
  return settings.mode === "live" ? (
    <button
      className="text-button public-refresh"
      disabled={loading}
      onClick={onRefresh}
    >
      {label}
    </button>
  ) : null;
}
