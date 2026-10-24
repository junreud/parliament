import { useState } from "react";
import { Browser } from "@capacitor/browser";
import { Capacitor } from "@capacitor/core";
import { dateLabel } from "../../../web/src/lib/format";
import { lawDate, lawSource } from "../laws";
import type { LawsState } from "../useLaws";
import { Icon } from "../components/Icon";

export function LawDetailScreen({
  id,
  laws,
  onBack,
}: {
  id: string;
  laws: LawsState;
  onBack: () => void;
}) {
  const [sourceError, setSourceError] = useState("");
  const law = laws.page?.items.find((item) => item.id === id);
  const source = law ? lawSource(law) : null;
  return (
    <>
      <div className="detail-toolbar">
        <button className="icon-button" aria-label="뒤로" onClick={onBack}>
          <Icon name="back" />
        </button>
        <span>법령 기본정보</span>
        <span className="law-source-tag">
          {laws.live ? "공개 API" : "실제 수집본"}
        </span>
      </div>
      {laws.status === "loading" ? (
        <p className="loading-state" role="status">
          법령을 읽고 있어요.
        </p>
      ) : !law ? (
        <section className="empty-state">
          <h1>
            {laws.status === "ok"
              ? "이 목록에 공개된 법령이 없어요"
              : "법령을 불러오지 못했어요"}
          </h1>
          <p>자료 연결 상태와 공개 목록을 확인해 주세요.</p>
          <button className="secondary-button" onClick={laws.reload}>
            법령 다시 불러오기
          </button>
        </section>
      ) : (
        <>
          <section className="detail-heading">
            <h1>{law.title}</h1>
            <p>
              {law.agency || "소관부처 미확인"} · 공포번호{" "}
              {law.promulgationNumber || "미확인"}
            </p>
          </section>
          <dl className="law-dates">
            <div>
              <dt>공포일</dt>
              <dd>{lawDate(law.promulgatedDate)}</dd>
            </div>
            <div>
              <dt>시행일</dt>
              <dd>{lawDate(law.effectiveDate)}</dd>
            </div>
          </dl>
          <section className="meaning-note">
            <Icon name="shield" size={20} />
            <p>
              이 버전의 원문에 적힌 날짜예요. 현재 시행 중인 법령인지와 조문별
              적용 시점은 공식 원문에서 확인해 주세요.
            </p>
          </section>
          <section className="detail-section">
            <div className="section-title">
              <h2>공식 원문</h2>
              <span>국가법령정보센터</span>
            </div>
            <p className="secondary-text">
              법령 일련번호 {law.mst}로 고정한 버전을 열어요.
            </p>
            {source && (
              <a
                className="secondary-button wide law-source-link"
                href={source}
                target="_blank"
                rel="noopener noreferrer"
                onClick={(event) => {
                  if (!Capacitor.isNativePlatform()) return;
                  event.preventDefault();
                  void Browser.open({
                    url: source,
                    toolbarColor: "#ffffff",
                  }).catch(() =>
                    setSourceError("원문을 열지 못했어요. 다시 시도해 주세요."),
                  );
                }}
              >
                국가법령정보센터 원문 <Icon name="external" size={17} />
              </a>
            )}
            {sourceError && (
              <p role="status" className="form-message">
                {sourceError}
              </p>
            )}
          </section>
          <section className="detail-section">
            <h2>원문에서 확인한 기본정보</h2>
            <div className="law-evidence-list">
              {law.evidence.map((evidence) => (
                <article className="evidence-item" key={evidence.locator}>
                  <strong>{evidence.label}</strong>
                  <blockquote>{evidence.text}</blockquote>
                  <p>원문 위치 · {evidence.locator}</p>
                </article>
              ))}
            </div>
          </section>
          <section className="detail-section">
            <h2>자료 범위와 버전</h2>
            <p className="secondary-text">
              {laws.page?.coverage} 조문 요약은 아직 제공하지 않아요.
              {!laws.live &&
                " 이 화면은 앱에 포함한 수집본이며 실시간 조회가 아니에요."}
            </p>
            <dl className="date-list law-version-list">
              <div>
                <dt>수집일</dt>
                <dd>{dateLabel(law.collectedAt)}</dd>
              </div>
              <div>
                <dt>법령 ID</dt>
                <dd>{law.lawId}</dd>
              </div>
              <div>
                <dt>원문 SHA-256</dt>
                <dd>{law.sourceVersion}</dd>
              </div>
              <div>
                <dt>추출 버전</dt>
                <dd>{law.extractionVersion}</dd>
              </div>
            </dl>
            <p className="law-scope">
              출처: 법제처 국가법령정보센터 · 기본정보의 날짜 정밀도는 일
              단위입니다.
            </p>
          </section>
        </>
      )}
    </>
  );
}
