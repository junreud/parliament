import { motionReduced } from "../motion";

export function ReadingIndex({ items }: { items: [string, string][] }) {
  return (
    <nav className="reading-index" aria-label="기록 목차">
      <span>이 글에서</span>
      <div>
        {items.map(([id, label]) => (
          <button
            key={id}
            onClick={() => {
              const target = document.getElementById(id);
              if (!target) return;
              target.focus({ preventScroll: true });
              target.scrollIntoView({
                block: "start",
                behavior: motionReduced() ? "instant" : "smooth",
              });
            }}
          >
            {label}
          </button>
        ))}
      </div>
    </nav>
  );
}
