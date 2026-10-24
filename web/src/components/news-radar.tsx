"use client";
import { useState } from "react";
import {
  GROWTH,
  radarTime,
  radarStale,
  radarSource,
  type RadarPage,
} from "@/lib/radar";
export function NewsRadar({ page }: { page: RadarPage }) {
  const [open, setOpen] = useState<string | null>(null);
  return (
    <section className="news-radar">
      <p className="radar-dateline">
        {radarTime(page.generatedAt)} 수집 · 최근 72시간 정치 뉴스
      </p>
      {(radarStale(page.generatedAt) || page.status === "unavailable") && (
        <p className="news-warning" role="status">
          최신 수집을 확인하지 못했습니다. 표시된 수집 시각을 확인해 주세요.
        </p>
      )}
      {page.status === "partial" && (
        <p className="news-warning" role="status">
          일부 매체 수집에 실패했습니다. 확인한 출처의 자료만 표시합니다.
        </p>
      )}
      <p className="news-notice">
        보도의 제목과 출처를 묶은 탐색 후보입니다. 보도량·검색량은 사실 확인이나
        국민 여론을 뜻하지 않습니다.
      </p>
      <div className="news-grid">
        {page.items.map((item, index) => (
          <article className="news-card" key={item.id}>
            <span className="news-index">
              {String(index + 1).padStart(2, "0")}
            </span>
            <div>
              <p className="news-meta">
                {item.publisherCount}개 매체 · {GROWTH[item.growth.status]}
              </p>
              <h2>{item.title}</h2>
              <p>{item.reason}</p>
              <button
                className="news-expand"
                aria-expanded={open === item.id}
                aria-controls={item.id}
                onClick={() => setOpen(open === item.id ? null : item.id)}
              >
                {open === item.id ? "접기" : "맥락과 보도 원문 보기"} →
              </button>
              {open === item.id && (
                <section id={item.id} className="news-expanded">
                  <h3>서로 다른 보도 읽기</h3>
                  {item.articles.map((a) => {
                    const url = radarSource(a.url, a.publisher);
                    return (
                      url && (
                        <a
                          key={url}
                          className="news-source"
                          href={url}
                          target="_blank"
                          rel="noopener noreferrer"
                        >
                          <small>
                            {a.publisher} · {radarTime(a.publishedAt)}
                          </small>
                          <strong>{a.title}</strong>
                          <span>언론사 원문 읽기 ↗</span>
                        </a>
                      )
                    );
                  })}
                  <div className="news-verification">
                    <h3>공식 기록은 어디까지?</h3>
                    <p>
                      이 후보의 공식 원문은 편집 검토 전입니다. 기사 속
                      주장·의혹과 실제 결정은 구분해 읽어 주세요.
                    </p>
                    <p>
                      발의와 통과, 수사와 유죄, 발표와 시행은 서로 다른
                      단계입니다.
                    </p>
                  </div>
                </section>
              )}
            </div>
          </article>
        ))}
      </div>
      {!page.items.length && (
        <p className="news-notice">조건에 맞는 새 이슈가 없습니다.</p>
      )}
      <details className="news-method">
        <summary>수집 범위와 선정 방식</summary>
        <p>
          규칙 기반으로 같은 URL·유사 제목을 묶고, 매체 수·다른 제목·공공정책
          설명 가치를 참고합니다. 자동 묶음에는 다른 사건이 포함될 수 있습니다.
          초기 12시간은 증가세를 비교하지 않습니다.
        </p>
        {page.sources.map((s) => (
          <p key={s.name}>
            {s.name}:{" "}
            {s.status === "ok" ? `${s.items}개 유효 항목` : "수집 실패"}
          </p>
        ))}
        <p>날짜 없는 기사 제외 · 게시 추천은 별도 원문 검수 · 자동 게시 없음</p>
      </details>
    </section>
  );
}
