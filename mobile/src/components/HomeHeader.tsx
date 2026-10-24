import { Icon } from "./Icon";

export function HomeReadingIntro() {
  return (
    <section className="home-intro">
      <h2>
        지금 어느 단계인지 <em>기록으로 확인하세요</em>
      </h2>
    </section>
  );
}

export function HomeHeader({
  topics,
  feed,
  onFeed,
  onTopics,
}: {
  topics: number;
  feed: string;
  onFeed: (feed: string) => void;
  onTopics: () => void;
}) {
  return (
    <>
      <div className="home-controls">
        <div className="feed-tabs" role="group" aria-label="피드 선택">
          <span
            className="feed-indicator"
            aria-hidden="true"
            style={{
              transform: `translateX(${feed === "interests" ? 100 : 0}%)`,
            }}
          />
          <button aria-pressed={feed === "all"} onClick={() => onFeed("all")}>
            전체 기록
          </button>
          <button
            aria-label="내 관심"
            aria-pressed={feed === "interests"}
            onClick={() => onFeed("interests")}
          >
            내 관심 {topics > 0 && <span aria-hidden="true">{topics}</span>}
          </button>
        </div>
        <button
          className="home-interest"
          aria-label="관심 주제 설정"
          onClick={onTopics}
        >
          <Icon name="spark" size={16} /> 관심 설정
        </button>
      </div>
    </>
  );
}
