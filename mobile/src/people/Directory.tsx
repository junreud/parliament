import { useState } from "react";
import type { DirectoryPerson } from "../../../web/src/lib/graph-contracts";
import type { Settings } from "../state";
import { useReadingView } from "../navigation";
import { usePages } from "./data";
import { Icon } from "../components/Icon";
import { OfficeDates } from "./PublicMeta";

export function PeopleDirectoryScreen({
  settings,
  entryId,
  onPerson,
  onBack,
}: {
  settings: Settings;
  entryId: string;
  onPerson: (id: string) => void;
  onBack: () => void;
}) {
  const [view, setView] = useReadingView(`directory:${entryId}`, {
    query: "",
    pages: 1,
  });
  const [query, setQuery] = useState(view.query);
  const path = `/api/v1/knowledge/people?${new URLSearchParams({ limit: "40", ...(view.query ? { query: view.query } : {}) })}`;
  const records = usePages<DirectoryPerson>(settings, path, view.pages);
  return (
    <>
      <div className="detail-toolbar">
        <button className="icon-button" aria-label="뒤로" onClick={onBack}>
          <Icon name="back" />
        </button>
        <span>인물 찾기</span>
        {settings.mode === "live" && (
          <button
            className="text-button public-refresh"
            disabled={records.status === "loading"}
            onClick={records.reload}
          >
            공개 목록 새로고침
          </button>
        )}
      </div>
      <div className="screen-title">
        <h1>인물</h1>
        <p>이름과 소속을 함께 확인해 주세요.</p>
      </div>
      {settings.mode === "preview" && (
        <p className="person-sample-note">
          가상 인물 · UX 예시예요. 실제 공직자 명부가 아니에요.
        </p>
      )}
      <form
        className="search-form"
        role="search"
        onSubmit={(event) => {
          event.preventDefault();
          setView({ query: query.trim().slice(0, 100), pages: 1 });
        }}
      >
        <Icon name="search" size={20} />
        <input
          type="search"
          aria-label="인물 이름 검색"
          placeholder="인물 이름으로 검색"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          maxLength={100}
        />
        <button className="icon-button" aria-label="인물 검색하기">
          <Icon name="arrow" size={19} />
        </button>
      </form>
      {records.status === "loading" ? (
        <p className="loading-state" role="status">
          인물을 찾고 있어요.
        </p>
      ) : records.status !== "ok" ? (
        <section className="empty-state" role="alert">
          <h2>
            {records.partial
              ? "일부 인물 목록을 불러오지 못했어요"
              : records.status === "not-found"
                ? "인물 목록 경로를 찾지 못했어요"
                : "인물 목록을 불러오지 못했어요"}
          </h2>
          <p>
            {records.partial
              ? "확인한 앞 페이지는 아래에 유지했어요. 다음 페이지를 다시 확인해 주세요."
              : records.status === "not-found"
                ? "404 응답을 받았어요. 연결한 서버의 공개 API 경로를 확인해 주세요."
                : "연결 실패는 공개 인물이 없다는 뜻이 아니에요."}
          </p>
          <button className="secondary-button" onClick={records.reload}>
            인물 목록 재시도
          </button>
        </section>
      ) : !records.items.length ? (
        <section className="empty-state">
          <h2>
            {view.query
              ? "조건에 맞는 공개 인물이 없어요"
              : "아직 공개된 인물이 없어요"}
          </h2>
          <p>
            현재 공개된 범위에서 확인되지 않았어요. 인물이나 활동이 존재하지
            않는다는 뜻은 아니에요.
          </p>
          <button
            className="secondary-button"
            onClick={() => {
              setQuery("");
              setView({ query: "", pages: 1 });
            }}
          >
            인물 검색 초기화
          </button>
        </section>
      ) : null}
      {records.status !== "loading" && records.items.length > 0 && (
        <div className="person-directory">
          {records.items.map((person) => (
            <button
              className="person-card"
              key={person.id}
              data-reader-focus={`directory-${person.id}`}
              aria-label={`${person.name} 인물 문서`}
              onClick={() => onPerson(person.id)}
            >
              <span className="person-avatar">{person.name.slice(0, 1)}</span>
              <div>
                <h2>{person.name}</h2>
                <p>
                  {[person.organizationName, person.position]
                    .filter(Boolean)
                    .join(" · ") || "소속·직위 확인 중"}
                </p>
                <OfficeDates observedAt={person.observedAt} />
              </div>
              <Icon name="arrow" size={18} />
            </button>
          ))}
        </div>
      )}
      {records.nextCursor && records.status === "ok" && (
        <button
          className="secondary-button wide"
          onClick={() => setView({ ...view, pages: view.pages + 1 })}
        >
          다음 인물 보기
        </button>
      )}
      <p className="person-coverage">
        명부 확보와 과거 활동 수집 범위는 달라요. 같은 이름만으로 다른 사람의
        기록을 합치지 않아요.
      </p>
    </>
  );
}
