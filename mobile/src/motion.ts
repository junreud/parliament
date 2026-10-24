import { flushSync } from "react-dom";

export const TAB_ORDER = ["home", "explore", "saved", "settings"];
let sequence = 0;
let currentTransition: ViewTransition | undefined;
let currentAnimation: Animation | undefined;

export function motionReduced() {
  return (
    window.matchMedia("(prefers-reduced-motion: reduce)").matches ||
    document
      .querySelector(".app-shell")
      ?.getAttribute("data-reduced-motion") === "true"
  );
}

export function routeDirection(previous: string, next: string) {
  const detail = (route: string) =>
    /^(activity|law|person|evidence|connections|bill|issue)\//.test(route);
  if (detail(next)) return 1;
  if (detail(previous)) return -1;
  return TAB_ORDER.indexOf(next) < TAB_ORDER.indexOf(previous) ? -1 : 1;
}

/** Keep routing synchronous in snapshots, and let the last tap own the transition. */
export function changeScreen(
  update: () => void,
  direction: number,
  scrollY = 0,
) {
  const token = ++sequence;
  currentTransition?.skipTransition();
  currentAnimation?.cancel();
  const screen = document.querySelector<HTMLElement>(".screen");
  const root = document.documentElement;
  root.dataset.motionDirection = direction < 0 ? "back" : "forward";
  root.style.setProperty("--flow-direction", String(direction));
  const commit = () => {
    if (token !== sequence) return;
    flushSync(update);
    window.scrollTo({ top: scrollY, behavior: "instant" });
  };
  const settle = () => {
    if (token === sequence && screen) screen.dataset.motionPhase = "idle";
  };
  if (!screen || motionReduced()) {
    root.dataset.motionKind = "none";
    if (screen) {
      screen.dataset.motionKind = "none";
      screen.dataset.motionPhase = "idle";
    }
    commit();
    return;
  }
  if (document.startViewTransition) {
    root.dataset.motionKind = "view-transition";
    screen.dataset.motionKind = "view-transition";
    screen.dataset.motionPhase = "entering";
    const transition = document.startViewTransition(commit);
    currentTransition = transition;
    void transition.ready.catch(() => {});
    void transition.finished.then(settle, settle);
    return;
  }
  root.dataset.motionKind = "fallback";
  screen.dataset.motionKind = "fallback";
  screen.dataset.motionPhase = "leaving";
  const exit = screen.animate(
    [
      { opacity: 1, transform: "translateX(0)" },
      { opacity: 0, transform: `translateX(${-direction * 12}px)` },
    ],
    { duration: 110, easing: "ease-in", fill: "forwards" },
  );
  currentAnimation = exit;
  void exit.finished
    .catch(() => {})
    .then(() => {
      if (token !== sequence) return;
      commit();
      exit.cancel();
      screen.dataset.motionPhase = "entering";
      const enter = screen.animate(
        [
          { opacity: 0, transform: `translateX(${direction * 28}px)` },
          { opacity: 1, transform: "translateX(0)" },
        ],
        { duration: 300, easing: "cubic-bezier(.22,1,.36,1)" },
      );
      currentAnimation = enter;
      void enter.finished.then(settle, settle);
    });
}
