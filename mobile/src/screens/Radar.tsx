import { Browser } from "@capacitor/browser";
import { Capacitor } from "@capacitor/core";
import {
  GROWTH,
  radarSource,
  radarStale,
  radarTime,
  type NewsArticle,
} from "../../../web/src/lib/radar";
import type { RadarState } from "../useRadar";
import { Icon } from "../components/Icon";
function ArticleLink({ article }: { article: NewsArticle }) {
  const url = radarSource(article.url, article.publisher);
  if (!url) return null;
  return (
    <a
      href={url}
      target="_blank"
      rel="noopener noreferrer"
      className="radar-source"
      onClick={(event) => {
        if (Capacitor.isNativePlatform()) {
          event.preventDefault();
          void Browser.open({ url }).catch(() => {});
        }
      }}
    >
      <span>
        {article.publisher}{" "}
        <time dateTime={article.publishedAt}>
          {radarTime(article.publishedAt)}
        </time>
      </span>
      <strong>{article.title}</strong>
      <small>언론사 원문 읽기 ↗</small>
    </a>
  );
}
export function RadarEntry({
  radar,
  onOpen,
}: {
  radar: RadarState;
  onOpen: () => void;
}) {
  return (
    <button className="radar-entry" onClick={onOpen}>
      <span className="radar-mark">
        <Icon name="search" size={20} />
      </span>
      <span>
        <strong>뉴스에서 포착한 이슈 후보</strong>
        <small>
          {radar.page
            ? `공식 근거 검토 전 · ${radar.page.items.length}개 후보 · ${radarTime(radar.page.generatedAt)}`
            : "공식 근거 검토 전 · 언론 보도에서 찾은 후보"}
        </small>
        <span className="radar-entry-action">기사와 출처 확인</span>
      </span>
      <Icon name="arrow" size={17} />
    </button>
  );
}
export function RadarScreen({
  radar,
  id,
  onBack,
  onOpen,
  home = false,
  onAll,
}: {
  radar: RadarState;
  id?: string;
  onBack: () => void;
  onOpen: (id: string) => void;
  home?: boolean;
  onAll?: () => void;
}) {
  const page = radar.page;
  const item = id ? page?.items.find((i) => i.id === id) : null;
  return (
    <div className={`radar-screen ${home ? "home-radar" : ""}`}>
      {!home && (
        <button className="back-button" onClick={onBack}>
          <Icon name="back" size={20} /> 뒤로
        </button>
      )}
      <div className="screen-title">
        {!home && (
          <span className="eyebrow">언론 보도 수집본 · 공식 근거 검토 전</span>
        )}
        <h1>
          {id ? "이슈 후보의 보도 근거" : home ? "화제 이슈" : "뉴스 이슈 후보"}
        </h1>
        <p>
          {home
            ? "최근 72시간 · 보도 신호와 편집 규칙으로 정한 후보"
            : "기사 묶음과 출처를 살펴보세요."}
        </p>
      </div>
      {radar.status === "loading" ? (
        <p role="status" className="radar-notice">
          뉴스 후보를 불러오는 중이에요.
        </p>
      ) : radar.status !== "ok" ? (
        <section className="empty-state error-state">
          <h2>
            {radar.status === "not-found"
              ? "뉴스 후보 경로를 찾지 못했어요"
              : "뉴스 후보를 불러오지 못했어요"}
          </h2>
          <p>
            잠시 후 다시 시도해 주세요. 문제가 계속되면 네트워크 연결을 확인해
            주세요.
          </p>
          <button className="secondary-button" onClick={radar.reload}>
            뉴스 후보 재시도
          </button>
        </section>
      ) : (
        page && (
          <>
            <div className="radar-meta">
              <span>
                {radar.live ? "서버 수집 자료" : "기기에 포함된 뉴스 수집본"}
              </span>
              <time dateTime={page.generatedAt}>
                {radarTime(page.generatedAt)} 기준
              </time>
            </div>
            {(radarStale(page.generatedAt) ||
              page.status === "unavailable") && (
              <p role="status" className="radar-warning">
                최신 수집을 확인하지 못했어요. 아래는{" "}
                {radarTime(page.generatedAt)}에 수집한 자료예요.
              </p>
            )}
            {page.status === "partial" && (
              <p role="status" className="radar-warning">
                일부 출처 수집에 실패했어요. 확인한 매체의 자료만 보여드려요.
              </p>
            )}
            <p className="radar-notice">
              {home
                ? "공식 근거 검토 전 · 보도량은 사실의 확실성이나 여론이 아니에요."
                : "언론 보도를 묶은 탐색 후보예요. 보도량은 사실의 확실성이나 여론을 뜻하지 않아요."}
            </p>
            {id ? (
              item ? (
                <article className="radar-detail">
                  <span className="radar-tag">
                    언론 보도 · 공식 근거 검토 전
                  </span>
                  <h2>{item.title}</h2>
                  <p className="radar-question">{item.question}</p>
                  <section>
                    <h3>이 이슈를 고른 이유</h3>
                    <p>{item.reason}</p>
                    <div className="radar-signals">
                      <span>{item.articleCount}개 기사</span>
                      <span>{item.publisherCount}개 매체</span>
                      <span>{GROWTH[item.growth.status]}</span>
                    </div>
                    <p className="radar-small">
                      유사한 제목은 중복 신호에서 제외해요. 기사 묶음은 자동
                      분류라 다른 사건이 포함될 수 있어요.
                    </p>
                  </section>
                  {item.searchSignals.length > 0 && (
                    <section>
                      <h3>함께 관측된 검색 관심</h3>
                      {item.searchSignals.map((t) => (
                        <p key={t.keyword}>
                          {t.keyword} · 피드 표기 {t.traffic}
                        </p>
                      ))}
                      <p className="radar-small">
                        구글 검색 급상승 신호이며 정치 여론조사가 아니에요.
                      </p>
                    </section>
                  )}
                  <section>
                    <h3>서로 다른 보도 읽기</h3>
                    <div className="radar-sources">
                      {item.articles.map((a) => (
                        <ArticleLink key={a.url} article={a} />
                      ))}
                    </div>
                  </section>
                  <section className="radar-check">
                    <h3>공식 기록은 어디까지?</h3>
                    <p>
                      이 후보의 공식 원문은 아직 편집 검토 전이에요. 기사 속
                      주장·의혹과 실제 결정은 구분해 읽어 주세요.
                    </p>
                    <p className="radar-small">
                      발의와 통과, 수사와 유죄, 발표와 시행은 서로 다른
                      단계예요.
                    </p>
                  </section>
                </article>
              ) : (
                <p className="radar-notice">
                  이번 수집본에서 이 후보를 찾지 못했어요. 목록에서 다시 골라
                  주세요.
                </p>
              )
            ) : page.items.length ? (
              <div className="radar-list">
                {page.items
                  .slice(0, home ? 3 : page.items.length)
                  .map((item, index) => (
                    <button
                      className="radar-card"
                      key={item.id}
                      data-reader-focus={`radar-${item.id}`}
                      onClick={() => onOpen(item.id)}
                    >
                      <span className="radar-number">
                        {String(index + 1).padStart(2, "0")}
                      </span>
                      <span>
                        <small>
                          {item.publisherCount}개 매체 ·{" "}
                          {GROWTH[item.growth.status]}
                        </small>
                        <strong>{item.title}</strong>
                        {!home && (
                          <span>
                            기사 묶음과 출처 보기{" "}
                            <Icon name="arrow" size={14} />
                          </span>
                        )}
                      </span>
                    </button>
                  ))}
              </div>
            ) : (
              <section className="empty-state">
                <h2>조건에 맞는 새 이슈가 없어요</h2>
                <p>최근 72시간의 유효한 보도만 후보로 모아요.</p>
              </section>
            )}
            {home && (
              <button className="home-radar-all" onClick={onAll || onBack}>
                후보 전체 · 기사와 선정 방식 <Icon name="arrow" size={14} />
              </button>
            )}
            {!home && (
              <details className="radar-coverage">
                <summary>수집 범위와 선정 방식</summary>
                <p>
                  최근 72시간 정치 RSS · 기사 제목 유사도로 묶음 · 매체 수·서로
                  다른 제목·공공정책 설명 가치 순으로 후보를 정리해요. 사람이
                  검토한 게시 추천과는 구분해요.
                </p>
                <p>
                  보도 신호에 설명 가치 등 편집 규칙을 더한 순서예요. 순수
                  보도량 순위나 국민 관심도·지지도 순위가 아니에요.
                </p>
                {page.sources.map((s) => (
                  <p key={s.name}>
                    {s.name} ·{" "}
                    {s.status === "ok" ? `${s.items}개 유효 항목` : "수집 실패"}
                  </p>
                ))}
                <p>
                  날짜가 없는 기사 제외 · 초기 12시간은 증가세 비교 보류 · 자동
                  게시 없음
                </p>
              </details>
            )}
          </>
        )
      )}
    </div>
  );
}
