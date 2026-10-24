import { lawDate } from "../laws";
import type { LawsState } from "../useLaws";
import { dateLabel } from "../../../web/src/lib/format";
import { Icon } from "./Icon";

export function LawShelf({
  laws,
  onOpen,
  showReload = true,
}: {
  laws: LawsState;
  onOpen: (id: string) => void;
  showReload?: boolean;
}) {
  return (
    <section className="law-shelf" aria-labelledby="law-shelf-title">
      <div className="section-title">
        <h2 id="law-shelf-title">법령 기본정보</h2>
        <span className="law-source-tag">
          {laws.live ? "공개 API" : "실제 수집본"}
        </span>
      </div>
      <p className="law-scope">
        {laws.live
          ? "공개 검수된 기본정보를 확인해요."
          : "앱에 포함한 수집 자료예요. 실시간 조회는 아니에요."}
        {laws.page?.items.length ? ` · ${laws.page.items.length}건` : ""}
      </p>
      {laws.status === "loading" ? (
        <p role="status" className="law-empty">
          법령을 읽고 있어요.
        </p>
      ) : laws.status !== "ok" ? (
        <div className="law-empty" role="status">
          <p>
            {laws.status === "not-found"
              ? "법령 공개 API를 찾지 못했어요"
              : "법령을 불러오지 못했어요"}
          </p>
          {showReload && (
            <button className="text-button" onClick={laws.reload}>
              법령 다시 불러오기
            </button>
          )}
        </div>
      ) : !laws.page?.items.length ? (
        <p className="law-empty">공개된 법령이 아직 없어요</p>
      ) : (
        <div className="law-list">
          {laws.page.items.map((law) => (
            <button
              className="law-card"
              key={law.id}
              aria-label={`${law.title} 기본정보 보기`}
              onClick={() => onOpen(law.id)}
            >
              <div className="law-card-heading">
                <span className="law-glyph">
                  <Icon name="economy-tax" size={22} />
                </span>
                <div>
                  <h3>{law.title}</h3>
                  <p>{law.agency || "소관부처 미확인"}</p>
                </div>
                <Icon name="arrow" size={17} />
              </div>
              <div className="law-card-dates">
                <span>
                  공포 <strong>{lawDate(law.promulgatedDate)}</strong>
                </span>
                <span>
                  시행일 <strong>{lawDate(law.effectiveDate)}</strong>
                </span>
              </div>
            </button>
          ))}
        </div>
      )}
      {!!laws.page?.items.length && (
        <p className="law-scope law-collected">
          {dateLabel(laws.page.items[0].collectedAt)} 수집 · 선택한 법령 버전의
          기본정보
        </p>
      )}
    </section>
  );
}
