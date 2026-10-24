import { useEffect, useRef, useState } from "react";
import { TOPICS } from "../../../web/src/lib/format";
import { Icon, type IconName } from "./Icon";
import { motionReduced } from "../motion";
export function TopicSheet({
  topics,
  onChange,
  onClose,
}: {
  topics: string[];
  onChange: (topics: string[]) => void;
  onClose: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const closing = useRef(false);
  const [state, setState] = useState("open");
  const exit = useRef<Animation | null>(null);
  const close = () => {
    if (closing.current) return;
    closing.current = true;
    if (!dialog.current || motionReduced()) {
      onClose();
      return;
    }
    setState("closing");
    const style = getComputedStyle(dialog.current);
    const animation = dialog.current.animate(
      [
        { opacity: style.opacity, transform: style.transform },
        { opacity: 0, transform: "translateY(32px)" },
      ],
      { duration: 190, easing: "cubic-bezier(.4,0,1,1)", fill: "forwards" },
    );
    exit.current = animation;
    void animation.finished.then(onClose, () => {});
  };
  useEffect(() => {
    const focused = document.activeElement as HTMLElement | null;
    dialog.current?.showModal();
    return () => {
      exit.current?.cancel();
      focused?.focus();
    };
  }, []);
  return (
    <dialog
      ref={dialog}
      className="topic-sheet"
      data-state={state}
      aria-labelledby="topic-sheet-title"
      onCancel={(event) => {
        event.preventDefault();
        close();
      }}
      onClick={(event) => {
        if (event.target === event.currentTarget) close();
      }}
    >
      <div className="sheet-handle" />
      <div className="sheet-heading">
        <h2 id="topic-sheet-title">어떤 변화가 궁금하세요?</h2>
        <button
          className="icon-button"
          aria-label="관심 주제 닫기"
          onClick={close}
        >
          <Icon name="close" />
        </button>
      </div>
      <p className="secondary-text">
        관심 있는 주제를 골라 주세요.
        <br />
        언제든지 다시 바꿀 수 있어요.
      </p>
      <div className="sheet-topics">
        {Object.entries(TOPICS).map(([id, label]) => (
          <button
            key={id}
            className={`topic-choice ${topics.includes(id) ? "selected" : ""}`}
            aria-pressed={topics.includes(id)}
            onClick={() =>
              onChange(
                topics.includes(id)
                  ? topics.filter((topic) => topic !== id)
                  : [...topics, id],
              )
            }
          >
            <span className={`topic-icon ${id}`}>
              <Icon name={id as IconName} />
            </span>
            <strong>{label}</strong>
            <span className="choice-check">
              <Icon name="check" size={17} />
            </span>
          </button>
        ))}
      </div>
      <button className="primary-button wide" onClick={close}>
        {topics.length
          ? `${topics.length}개 주제와 함께 시작하기`
          : "모든 주제 둘러보기"}
        <Icon name="arrow" size={18} />
      </button>
      <p className="privacy-note">관심 주제는 이 기기에만 저장해요.</p>
    </dialog>
  );
}
