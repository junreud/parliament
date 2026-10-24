import { useEffect, useState } from "react";
import { App as NativeApp } from "@capacitor/app";
import { Capacitor } from "@capacitor/core";
import { Haptics, ImpactStyle } from "@capacitor/haptics";
import { TOPICS, TYPES } from "../../web/src/lib/format";
import {
  DEFAULT_SETTINGS,
  STORAGE_KEY,
  parseSettings,
  toggleSaved,
  type Settings,
} from "./state";
import { useRecords } from "./useRecords";
import { useLaws } from "./useLaws";
import { LawShelf } from "./components/LawShelf";
import { BillScreen } from "./screens/Bill";
import { IssueScreen } from "./screens/Issue";
import { LawDetailScreen } from "./screens/LawDetail";
import { Icon, type IconName } from "./components/Icon";
import { RecordCard } from "./components/RecordCard";
import { RecordSearch } from "./components/RecordSearch";
import { TopicSheet } from "./components/TopicSheet";
import { SettingsScreen } from "./screens/Settings";
import { DetailScreen } from "./screens/Detail";
import { HomeHeader, HomeReadingIntro } from "./components/HomeHeader";
import { ReviewedIssueEntry } from "./components/ReviewedIssueEntry";
import { TAB_ORDER } from "./motion";
import { useNavigation, readSession, writeSession } from "./navigation";
import { PersonScreen } from "./people/PersonScreen";
import { PeopleDirectoryScreen } from "./people/Directory";
import { PersonSheet } from "./people/PersonSheet";
import { EvidenceScreen, GraphScreen } from "./people/Reading";
import type { GraphKind } from "../../web/src/lib/graph-contracts";
import { useRadar } from "./useRadar";
import { RadarEntry, RadarScreen } from "./screens/Radar";
import "./radar.css";
type Tab = "home" | "explore" | "saved" | "settings";
export function App() {
  const [settings, setSettings] = useState<Settings>(() => {
    try {
      return parseSettings(localStorage.getItem(STORAGE_KEY));
    } catch {
      return structuredClone(DEFAULT_SETTINGS);
    }
  });
  const navigation = useNavigation();
  const { route, entryId, go, back } = navigation;
  const [sheet, setSheet] = useState(false);
  const [personPeek, setPersonPeek] = useState<string | null>(null);
  const [toast, setToast] = useState("");
  const initial = readSession("main-view", {
    topic: "",
    type: "",
    feed: "all",
    search: "",
    query: "",
  });
  const [topic, setTopic] = useState(initial.topic);
  const [type, setType] = useState(initial.type);
  const [feed, setFeed] = useState(initial.feed);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [search, setSearch] = useState(initial.search);
  const [query, setQuery] = useState(initial.query);
  const personId = route.startsWith("person/") ? route.slice(7) : null;
  const evidenceId = route.startsWith("evidence/") ? route.slice(9) : null;
  const issueId = route.startsWith("issue/") ? route.slice(6) : null;
  const graph = route.startsWith("connections/") ? route.split("/") : null;
  const tab: Tab = ["home", "explore", "saved", "settings"].includes(route)
    ? (route as Tab)
    : route === "people" || personId || graph
      ? "explore"
      : "home";
  const radarDetail = route.startsWith("radar/") ? route.slice(6) : undefined;
  const inRadar = route === "radar" || Boolean(radarDetail);
  const radar = useRadar(settings);
  const billDetail = route.startsWith("bill/") ? route.slice(5) : null;
  const lawDetail = route.startsWith("law/") ? route.slice(4) : null;
  const detail = route.startsWith("activity/") ? route.slice(9) : lawDetail;
  const inDetail = Boolean(
    detail ||
    billDetail ||
    personId ||
    evidenceId ||
    issueId ||
    graph ||
    inRadar,
  );
  const preview = settings.mode === "preview";
  const laws = useLaws(settings);
  const records = useRecords(settings, {
    topic: tab === "home" || tab === "explore" ? topic : "",
    type: tab === "home" ? type : "",
    query: tab === "explore" ? query : "",
    savedOnly: tab === "saved",
    interestsOnly: tab === "home" && feed === "interests",
  });
  useEffect(() => {
    setSheet(false);
    setPersonPeek(null);
    setFiltersOpen(false);
  }, [entryId]);
  useEffect(
    () => writeSession("main-view", { topic, type, feed, search, query }),
    [topic, type, feed, search, query],
  );
  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(""), 2600);
    return () => clearTimeout(timer);
  }, [toast]);
  useEffect(() => {
    if (!Capacitor.isNativePlatform()) return;
    const listener = NativeApp.addListener("backButton", () => {
      const sourceSheet = document.querySelector(".source-sheet[open]");
      if (sourceSheet) {
        sourceSheet.dispatchEvent(new Event("cancel", { cancelable: true }));
        return;
      }
      if (personPeek) {
        setPersonPeek(null);
        return;
      }
      if (sheet) {
        document
          .querySelector(".topic-sheet")
          ?.dispatchEvent(new Event("cancel", { cancelable: true }));
        return;
      }
      if (inDetail || route === "people") {
        back();
        return;
      }
      if (tab !== "home") {
        go("home");
        return;
      }
      void NativeApp.exitApp();
    });
    return () => {
      void listener.then((handle) => handle.remove());
    };
  }, [sheet, inDetail, tab, personPeek, entryId]);
  const change = (next: Settings) => {
    setSettings(next);
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
    } catch {
      setToast("기기에 저장하지 못했어요. 저장 공간을 확인해 주세요.");
    }
  };
  const save = (id: string) => {
    const next = toggleSaved(settings, id);
    if (next === settings) {
      setToast("최대 50개까지 저장할 수 있어요.");
      return;
    }
    const added = next.saved[next.mode].includes(id);
    change(next);
    setToast(added ? "기록을 저장했어요" : "저장을 해제했어요");
    if (settings.haptics && Capacitor.isNativePlatform())
      void Haptics.impact({ style: ImpactStyle.Light }).catch(() => {});
  };
  const open = (id: string) => go(`activity/${encodeURIComponent(id)}`);
  const openLaw = (id: string) => go(`law/${id}`);
  const previewPerson = (id: string) => {
    navigation.checkpoint();
    setPersonPeek(id);
  };
  const links = {
    onPerson: (id: string) => go(`person/${id}`),
    onActivity: open,
    onEvidence: (id: string) => go(`evidence/${id}`),
    onGraph: (kind: GraphKind, id: string) =>
      go(kind === "bill" ? `bill/${id}` : `connections/${kind}/${id}`),
  };
  const recordCards = records.records.map((record) => (
    <RecordCard
      key={record.id}
      record={record}
      preview={preview}
      saved={settings.saved[settings.mode].includes(record.id)}
      onSave={() => save(record.id)}
      onOpen={() => open(record.id)}
    />
  ));
  const recordsFailure = records.status !== "loading" &&
    records.status !== "ok" && (
      <section className="empty-state error-state">
        <span className="empty-symbol">
          <Icon name="refresh" size={30} />
        </span>
        <h2>
          {records.status === "not-found"
            ? "공개된 자료를 찾지 못했어요"
            : "기록을 불러오지 못했어요"}
        </h2>
        <p>
          {records.records.length
            ? "일부 저장 기록을 불러오지 못했어요. 아래에는 확인한 기록만 표시해요."
            : records.status === "not-found"
              ? "요청한 자료가 아직 공개되지 않았거나 주소가 바뀌었어요."
              : "잠시 후 다시 시도해 주세요. 문제가 계속되면 네트워크 연결을 확인해 주세요."}
        </p>
        <button
          className="secondary-button"
          onClick={() => {
            records.reload();
            laws.reload();
          }}
        >
          다시 불러오기
        </button>
      </section>
    );
  return (
    <div
      className="app-shell"
      data-font-size={settings.fontSize}
      data-reduced-motion={settings.reducedMotion}
    >
      <a
        className="skip-link"
        href="#main-content"
        onClick={(e) => {
          e.preventDefault();
          document.getElementById("main-content")?.focus();
        }}
      >
        본문으로 바로가기
      </a>
      <header className="app-header">
        <button
          className="brand"
          aria-label="의정의 흐름 홈"
          onClick={() => go("home")}
        >
          <img src="/icon.svg" width="30" height="30" alt="" />
          <span>의정의 흐름</span>
        </button>
      </header>
      <div className={`mode-banner ${preview ? "" : "live-banner"}`}>
        <span className="mode-dot" />
        <strong>
          {inRadar && preview
            ? "뉴스 수집 자료"
            : lawDetail && preview
              ? "법령 수집 자료"
              : preview
                ? "디자인 미리보기"
                : "공개 기록 모드"}
        </strong>
        <span>
          {preview
            ? inRadar
              ? "날짜와 출처를 확인한 뉴스 후보"
              : lawDetail
                ? "공식 원문에서 확인한 기본정보"
                : "활동은 화면 예시 · 법령은 실제 수집본"
            : "연결한 서버의 자료를 확인해요"}
        </span>
      </div>
      <main id="main-content" tabIndex={-1} className="main-content">
        <div className={route === "home" ? "screen home-screen" : "screen"}>
          {inRadar ? (
            <RadarScreen
              radar={radar}
              id={radarDetail}
              onBack={back}
              onOpen={(id) => go(`radar/${id}`)}
            />
          ) : issueId ? (
            <IssueScreen
              key={entryId}
              id={issueId}
              settings={settings}
              onBack={back}
              onPerson={previewPerson}
              onEvidence={links.onEvidence}
              onSettings={() => go("settings")}
              onPrepareReload={navigation.prepareReload}
            />
          ) : personId ? (
            <PersonScreen
              key={entryId}
              id={personId}
              entryId={entryId}
              settings={settings}
              onBack={back}
              {...links}
            />
          ) : evidenceId ? (
            <EvidenceScreen
              key={entryId}
              id={evidenceId}
              settings={settings}
              onBack={back}
              onPerson={previewPerson}
            />
          ) : graph ? (
            <GraphScreen
              key={entryId}
              kind={graph.length === 3 ? (graph[1] as GraphKind) : "person"}
              id={graph[graph.length - 1]}
              settings={settings}
              onBack={back}
              {...links}
            />
          ) : route === "people" ? (
            <PeopleDirectoryScreen
              key={entryId}
              entryId={entryId}
              settings={settings}
              onBack={back}
              onPerson={links.onPerson}
            />
          ) : billDetail ? (
            <BillScreen
              key={entryId}
              id={billDetail}
              settings={settings}
              onBack={back}
              onBill={(id) => go(`bill/${id}`)}
              onEvidence={links.onEvidence}
              onActivity={open}
            />
          ) : lawDetail ? (
            <LawDetailScreen id={lawDetail} laws={laws} onBack={back} />
          ) : detail ? (
            <DetailScreen
              key={entryId}
              id={decodeURIComponent(detail)}
              settings={settings}
              onBack={back}
              onSave={save}
              onPerson={previewPerson}
              onEvidence={links.onEvidence}
              onBill={(id) => go(`bill/${id}`)}
            />
          ) : tab === "settings" ? (
            <SettingsScreen
              settings={settings}
              onChange={change}
              onTopics={() => setSheet(true)}
            />
          ) : (
            <>
              {tab === "home" ? (
                <>
                  <RecordSearch
                    id="home-search"
                    value={search}
                    onChange={setSearch}
                    onSubmit={() => {
                      setQuery(search.trim());
                      go("explore");
                    }}
                  />
                  {recordsFailure}
                  <RadarScreen
                    home
                    radar={radar}
                    onBack={back}
                    onOpen={(id) => go(`radar/${id}`)}
                    onAll={() => go("radar")}
                  />
                  <HomeHeader
                    topics={settings.topics.length}
                    feed={feed}
                    onFeed={setFeed}
                    onTopics={() => setSheet(true)}
                  />
                </>
              ) : tab === "explore" ? (
                <>
                  <div className="screen-title">
                    <h1>탐색</h1>
                  </div>
                  <RecordSearch
                    id="explore-search"
                    value={search}
                    onChange={setSearch}
                    onSubmit={() => setQuery(search.trim())}
                  />
                  <button className="people-entry" onClick={() => go("people")}>
                    <span className="topic-icon family">
                      <Icon name="family" size={23} />
                    </span>
                    <span>
                      <strong>인물 위키 둘러보기</strong>
                      <small>소개와 시간순 이력</small>
                    </span>
                    <Icon name="arrow" size={18} />
                  </button>
                  {!query && (
                    <div className="explore-topics">
                      {Object.entries(TOPICS).map(([id, label]) => (
                        <button
                          key={id}
                          aria-pressed={topic === id}
                          onClick={() => setTopic(topic === id ? "" : id)}
                        >
                          <span className={`topic-icon ${id}`}>
                            <Icon name={id as IconName} size={24} />
                          </span>
                          <strong>{label}</strong>
                          <span>
                            {id === "family"
                              ? "돌봄과 지원"
                              : id === "housing"
                                ? "주거와 생활"
                                : id === "labor"
                                  ? "일자리와 권리"
                                  : "경제와 세금"}
                          </span>
                        </button>
                      ))}
                    </div>
                  )}
                  <div className="section-title">
                    <h2>
                      {query
                        ? `‘${query}’ 공개 기록 검색 결과`
                        : "주제별 공개 기록"}
                    </h2>
                    {(query || topic) && (
                      <button
                        className="text-button"
                        onClick={() => {
                          setQuery("");
                          setSearch("");
                          setTopic("");
                        }}
                      >
                        {query
                          ? topic
                            ? "검색·필터 지우기"
                            : "검색 지우기"
                          : "필터 해제"}
                      </button>
                    )}
                  </div>
                </>
              ) : (
                <>
                  <div className="screen-title">
                    <h1>저장한 기록</h1>
                  </div>
                  <div className="saved-count">
                    <Icon name="bookmark" size={17} />
                    <span>
                      이 기기에 {settings.saved[settings.mode].length}개 저장
                    </span>
                  </div>
                </>
              )}
              {tab === "home" && (
                <div className="home-list-toolbar">
                  <div className="home-records-heading">
                    <h2>{preview ? "화면 예시 기록" : "공개 기록"}</h2>
                  </div>
                  <details
                    className="home-filters"
                    onToggle={(event) =>
                      setFiltersOpen(event.currentTarget.open)
                    }
                  >
                    <summary
                      role="button"
                      aria-label="주제·유형 필터"
                      aria-expanded={filtersOpen}
                    >
                      <span>
                        {topic || type
                          ? `${TOPICS[topic] || "전체 주제"} · ${TYPES[type] || "모든 기록"}`
                          : "주제·유형 필터"}
                      </span>
                      <Icon name="arrow" size={15} />
                    </summary>
                    <div className="filters">
                      <div
                        className="topic-chips"
                        role="group"
                        aria-label="주제 필터"
                      >
                        <button
                          aria-pressed={!topic}
                          onClick={() => setTopic("")}
                        >
                          전체
                        </button>
                        {Object.entries(TOPICS).map(([id, label]) => (
                          <button
                            key={id}
                            aria-pressed={topic === id}
                            onClick={() => setTopic(id)}
                          >
                            {label}
                          </button>
                        ))}
                      </div>
                      <label className="type-filter">
                        <span className="sr-only">기록 유형</span>
                        <select
                          value={type}
                          onChange={(e) => setType(e.target.value)}
                        >
                          <option value="">모든 기록</option>
                          {Object.entries(TYPES).map(([id, label]) => (
                            <option key={id} value={id}>
                              {label}
                            </option>
                          ))}
                        </select>
                      </label>
                    </div>
                  </details>
                </div>
              )}
              {records.status === "loading" ? (
                <div
                  className="skeleton-list"
                  aria-label="기록 불러오는 중"
                  role="status"
                >
                  {[1, 2, 3].map((n) => (
                    <div key={n} className="skeleton-card">
                      <span />
                      <span />
                      <span />
                    </div>
                  ))}
                </div>
              ) : (
                <>
                  {tab !== "home" && recordsFailure}
                  {records.status === "ok" && !records.records.length && (
                    <section className="empty-state">
                      <span className="empty-symbol">
                        <Icon
                          name={tab === "saved" ? "bookmark" : "search"}
                          size={30}
                        />
                      </span>
                      <h2>
                        {tab === "saved"
                          ? "마음에 남은 기록을 저장해요"
                          : query
                            ? "다른 키워드로 찾아볼까요?"
                            : feed === "interests" && !settings.topics.length
                              ? "관심 주제를 골라 주세요"
                              : "아직 공개된 기록이 없어요"}
                      </h2>
                      <p>
                        {tab === "saved"
                          ? "기록의 북마크를 누르면 여기에서 다시 읽을 수 있어요."
                          : "선택한 조건에 맞는 기록이 없어요. 다른 주제나 조건도 살펴보세요."}
                      </p>
                      {tab === "saved" ? (
                        <button
                          className="secondary-button"
                          onClick={() => go("home")}
                        >
                          기록 둘러보기
                        </button>
                      ) : feed === "interests" && !settings.topics.length ? (
                        <button
                          className="secondary-button"
                          onClick={() => setSheet(true)}
                        >
                          관심 주제 고르기
                        </button>
                      ) : null}
                    </section>
                  )}
                  <div
                    className={`records-list ${tab === "home" ? "home-lead-list" : ""}`}
                  >
                    {tab === "home" ? recordCards.slice(0, 1) : recordCards}
                  </div>
                  {tab === "home" && (
                    <>
                      <HomeReadingIntro />
                      <ReviewedIssueEntry
                        settings={settings}
                        onOpen={(id) => go(`issue/${id}`)}
                      />
                      <section
                        className="home-news"
                        aria-label="뉴스 후보 전체"
                      >
                        <RadarEntry radar={radar} onOpen={() => go("radar")} />
                      </section>
                    </>
                  )}
                  {tab === "home" && recordCards.length > 1 && (
                    <div className="records-list home-more-list">
                      {recordCards.slice(1)}
                    </div>
                  )}
                  {tab === "home" && (
                    <LawShelf
                      laws={laws}
                      onOpen={openLaw}
                      showReload={records.status === "ok"}
                    />
                  )}
                  {records.moreError && (
                    <p className="inline-error" role="alert">
                      다음 기록을 불러오지 못했어요. 다시 시도해 주세요.
                    </p>
                  )}
                  {records.cursor && (
                    <button
                      className="secondary-button wide load-more"
                      onClick={() => void records.loadMore()}
                      disabled={records.moreBusy}
                    >
                      {records.moreBusy ? "불러오는 중…" : "다음 기록 읽기"}
                      <Icon name="arrow" size={17} />
                    </button>
                  )}
                  {tab === "home" && feed === "interests" && (
                    <p className="scope-note">
                      공개 피드에서 읽어 온 기록 중 관심 주제와 일치하는
                      기록이에요. 다음 기록도 이어서 확인할 수 있어요.
                    </p>
                  )}
                </>
              )}
              <div className="record-principle">
                <Icon name="shield" size={17} />
                <p>
                  발표와 시행을 구분하고,
                  <br />
                  모든 설명은 공식 근거에서 출발해요.
                </p>
              </div>
            </>
          )}
        </div>
      </main>
      <nav className="bottom-nav" aria-label="하단 메뉴">
        <span
          className="nav-active-indicator"
          aria-hidden="true"
          data-visible={!inDetail}
          style={{ transform: `translateX(${TAB_ORDER.indexOf(tab) * 100}%)` }}
        >
          <span />
        </span>
        {(
          [
            ["home", "home", "홈"],
            ["explore", "search", "탐색"],
            ["saved", "bookmark", "저장"],
            ["settings", "settings", "설정"],
          ] as [Tab, IconName, string][]
        ).map(([target, icon, label]) => (
          <button
            key={target}
            aria-current={!inDetail && tab === target ? "page" : undefined}
            onClick={() => go(target)}
          >
            <span className="nav-icon">
              <Icon name={icon} size={23} />
            </span>
            <span>{label}</span>
            {target === "saved" && settings.saved[settings.mode].length > 0 && (
              <i className="nav-dot" />
            )}
          </button>
        ))}
      </nav>
      {sheet && (
        <TopicSheet
          topics={settings.topics}
          onChange={(topics) => change({ ...settings, topics })}
          onClose={() => setSheet(false)}
        />
      )}
      {personPeek && (
        <PersonSheet
          id={personPeek}
          settings={settings}
          onClose={() => setPersonPeek(null)}
          onOpen={(id) => {
            setPersonPeek(null);
            links.onPerson(id);
          }}
        />
      )}
      <div
        className={`toast ${toast ? "visible" : ""}`}
        role={toast ? "status" : undefined}
        aria-live="polite"
      >
        {toast && (
          <>
            <Icon name="check" size={17} />
            {toast}
          </>
        )}
      </div>
    </div>
  );
}
