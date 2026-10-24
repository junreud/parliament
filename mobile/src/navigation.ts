import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { changeScreen, routeDirection } from "./motion";

const ENTRY = "parliament-reader";
export function sanitizeRoute(raw: string): string {
  if (["home", "explore", "people", "saved", "settings", "radar"].includes(raw))
    return raw;
  if (/^radar\/news_[a-f0-9]{16}$/.test(raw)) return raw;
  if (/^law\/law_[0-9]{1,12}_[0-9]{1,12}$/.test(raw)) return raw;
  if (
    /^(person|evidence|connections|bill|issue)\/[A-Za-z0-9_-]{1,128}$/.test(raw)
  )
    return raw;
  if (
    /^connections\/(person|organization|bill|policy|activity|document|issue)\/[A-Za-z0-9_-]{1,128}$/.test(
      raw,
    )
  )
    return raw;
  if (
    /^activity\/[A-Za-z0-9_.:-]{1,128}$/.test(raw) &&
    !/\/(\.|\.\.)$/.test(raw)
  )
    return raw;
  return "home";
}
type Entry = {
  id: string;
  index: number;
  route: string;
  y: number;
  focus: string | null;
  anchor?: { id: string; section: string | null; offset: number };
};
function readEntry(): Entry {
  const route = sanitizeRoute(location.hash.slice(1));
  const saved = history.state?.reader as Entry | undefined;
  if (
    saved &&
    saved.route === route &&
    typeof saved.id === "string" &&
    Number.isSafeInteger(saved.index)
  )
    return saved;
  const entry = {
    id: crypto.randomUUID(),
    index: saved ? saved.index + 1 : 0,
    route,
    y: 0,
    focus: null,
  };
  history.replaceState({ ...history.state, reader: entry }, "", `#${route}`);
  return entry;
}
export function readSession<T>(key: string, initial: T): T {
  try {
    const value = sessionStorage.getItem(`${ENTRY}:${key}`);
    return value ? (JSON.parse(value) as T) : initial;
  } catch {
    return initial;
  }
}
export function writeSession(key: string, value: unknown) {
  try {
    sessionStorage.setItem(`${ENTRY}:${key}`, JSON.stringify(value));
  } catch {
    /* Keep reading when storage is unavailable. */
  }
}
export function useReadingView<T>(key: string, initial: T) {
  const [value, setValue] = useState<T>(() => readSession(key, initial));
  const update = (next: T) => {
    writeSession(key, next);
    setValue(next);
  };
  return [value, update] as const;
}
/** Persist small reading controls separately for each browser history entry. */
export function useEntryView<T>(key: string, initial: T) {
  return useReadingView(
    `${history.state?.reader?.id || location.hash}:${key}`,
    initial,
  );
}
let pendingReadingLoads = 0;
export function beginReadingLoad() {
  pendingReadingLoads++;
  let finished = false;
  return () => {
    if (finished) return;
    finished = true;
    pendingReadingLoads--;
    window.dispatchEvent(new Event("parliament-reading-settled"));
  };
}
export function useNavigation() {
  const [entry, setEntry] = useState(readEntry);
  const [reloadCycle, setReloadCycle] = useState(0);
  const current = useRef(entry);
  const restoring = useRef(false);
  const save = () => {
    // An explicit navigation owns the current position even if the previous
    // restoration is still settling after a publication change.
    restoring.current = false;
    const focus =
      document.activeElement instanceof HTMLElement
        ? document.activeElement.dataset.readerFocus || null
        : null;
    const active =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    const reading = document.querySelector<HTMLElement>(
      "[data-reading-version]",
    );
    const anchor =
      reading &&
      (active?.closest<HTMLElement>("[data-reader-anchor]") ||
        Array.from(
          reading.querySelectorAll<HTMLElement>("[data-reader-anchor]"),
        ).find((el) => {
          const rect = el.getBoundingClientRect();
          return (
            el.getClientRects().length > 0 &&
            rect.bottom > 0 &&
            rect.top < innerHeight
          );
        }));
    const next = {
      ...current.current,
      y: window.scrollY,
      focus: focus || current.current.focus,
      anchor: anchor
        ? {
            id: anchor.dataset.readerAnchor!,
            section:
              anchor.closest<HTMLElement>("[data-reader-section]")?.dataset
                .readerSection || null,
            offset: -anchor.getBoundingClientRect().top,
          }
        : undefined,
    };
    current.current = next;
    writeSession(next.id, next);
    if (history.state?.reader?.id === next.id)
      history.replaceState({ ...history.state, reader: next }, "");
  };
  const show = (next: Entry, restore: boolean, revisit = false) => {
    const previous = current.current;
    restoring.current = restore || revisit;
    current.current = next;
    changeScreen(
      () => setEntry(next),
      restore ? -1 : routeDirection(previous.route, next.route),
      restore || revisit ? next.y : 0,
    );
  };
  useEffect(() => {
    history.scrollRestoration = "manual";
    const update = () => {
      const next = readEntry();
      if (next.id === current.current.id) return;
      const restore = next.index < current.current.index;
      const saved = readSession<Entry>(next.id, next);
      show(saved, restore, true);
    };
    const onScroll = () => {
      if (!restoring.current)
        writeSession(current.current.id, {
          ...current.current,
          y: window.scrollY,
        });
    };
    const pagehide = () => save();
    window.addEventListener("popstate", update);
    window.addEventListener("hashchange", update);
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("pagehide", pagehide);
    return () => {
      window.removeEventListener("popstate", update);
      window.removeEventListener("hashchange", update);
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("pagehide", pagehide);
    };
  }, []);
  useLayoutEffect(() => {
    const target = readSession<Entry>(entry.id, entry);
    if (!restoring.current && target.y === 0) return;
    restoring.current = true;
    let complete = false;
    let frame = 0;
    const restore = () => {
      if (complete) return;
      const maximum = Math.max(
        0,
        document.documentElement.scrollHeight - window.innerHeight,
      );
      const anchors = Array.from(
        document.querySelectorAll<HTMLElement>("[data-reader-anchor]"),
      );
      const anchor =
        target.anchor &&
        anchors.find(
          (el) =>
            el.dataset.readerAnchor === target.anchor?.id &&
            el.getClientRects().length > 0,
        );
      if (target.anchor && !anchor && pendingReadingLoads > 0) return;
      const fallback =
        target.anchor &&
        (Array.from(
          document.querySelectorAll<HTMLElement>("[data-reader-section]"),
        ).find(
          (el) =>
            el.dataset.readerSection === target.anchor?.section &&
            el.getClientRects().length > 0,
        ) ||
          anchors.find((el) => el.dataset.readerAnchor === "reading-top"));
      const requested =
        anchor && target.anchor && Number.isFinite(target.anchor.offset)
          ? window.scrollY +
            anchor.getBoundingClientRect().top +
            target.anchor.offset
          : fallback
            ? window.scrollY + fallback.getBoundingClientRect().top
            : target.y;
      // A fresh public version may be shorter or withdrawn. Wait for pending
      // requests, then clamp to the remaining document rather than waiting forever.
      if (maximum + 2 < requested && pendingReadingLoads > 0) return;
      window.scrollTo({
        top: Math.max(0, Math.min(requested, maximum)),
        behavior: "instant",
      });
      if (target.focus) {
        const trigger = Array.from(
          document.querySelectorAll<HTMLElement>("[data-reader-focus]"),
        ).find(
          (el) =>
            el.dataset.readerFocus === target.focus &&
            el.getClientRects().length > 0,
        );
        (
          trigger ||
          (target.anchor
            ? document.querySelector<HTMLElement>("[data-reading-fallback]")
            : null)
        )?.focus({ preventScroll: true });
      }
      complete = true;
      restoring.current = false;
      observer.disconnect();
    };
    // Two frames allow passive data effects and newly mounted child resources to register.
    const schedule = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        frame = requestAnimationFrame(restore);
      });
    };
    const observer = new ResizeObserver(schedule);
    observer.observe(document.getElementById("main-content") || document.body);
    window.addEventListener("parliament-reading-settled", schedule);
    schedule();
    return () => {
      observer.disconnect();
      cancelAnimationFrame(frame);
      window.removeEventListener("parliament-reading-settled", schedule);
    };
  }, [entry.id, reloadCycle]);
  const go = (route: string) => {
    const nextRoute = sanitizeRoute(route);
    if (nextRoute === current.current.route) return;
    save();
    const next = {
      id: crypto.randomUUID(),
      index: current.current.index + 1,
      route: nextRoute,
      y: 0,
      focus: null,
    };
    history.pushState(
      { reader: next, mobileDetail: true },
      "",
      `#${nextRoute}`,
    );
    show(next, false);
  };
  const back = () => {
    if (current.current.index > 0) {
      save();
      history.back();
    } else {
      const route = current.current.route.startsWith("person/")
        ? "people"
        : current.current.route === "people"
          ? "explore"
          : "home";
      const next = {
        id: crypto.randomUUID(),
        index: 0,
        route,
        y: 0,
        focus: null,
      };
      history.replaceState({ reader: next }, "", `#${route}`);
      show(next, true);
    }
  };
  const prepareReload = () => {
    save();
    restoring.current = true;
    setReloadCycle((value) => value + 1);
  };
  return {
    route: entry.route,
    entryId: entry.id,
    go,
    back,
    checkpoint: save,
    prepareReload,
  };
}
