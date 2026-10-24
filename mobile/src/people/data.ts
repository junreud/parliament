import { useEffect, useState } from "react";
import type { Settings } from "../state";
import type { Result } from "../api";
import { readKnowledge } from "./api";
import { previewResource } from "./preview";
import { beginReadingLoad } from "../navigation";

const cache = new Map<string, unknown>();
const keyFor = (settings: Settings, path: string) =>
  `${settings.mode}|${settings.origin}|${path}`;
function cached(settings: Settings, key: string) {
  return settings.mode === "preview" ? cache.get(key) : undefined;
}
function remember(settings: Settings, key: string, data: unknown) {
  if (settings.mode !== "preview") return;
  if (cache.size >= 160) cache.delete(cache.keys().next().value!);
  cache.set(key, data);
}
async function load<T>(settings: Settings, path: string): Promise<Result<T>> {
  const key = keyFor(settings, path);
  const previous = cached(settings, key);
  if (previous !== undefined) return { status: "ok", data: previous as T };
  const result: Result<T> =
    settings.mode === "preview"
      ? (() => {
          const data = previewResource(path);
          return data
            ? { status: "ok", data: data as T }
            : { status: "not-found" };
        })()
      : await readKnowledge<T>(settings.origin, path);
  if (result.status === "ok") remember(settings, key, result.data);
  return result;
}
export function useResource<T>(settings: Settings, path: string | null) {
  const key = keyFor(settings, path || "disabled");
  const [revision, setRevision] = useState(0);
  const [state, setState] = useState<{
    key: string;
    status: "loading" | "ok" | "error" | "not-found";
    data: T | null;
  }>(() => ({
    key,
    status: cached(settings, key) !== undefined ? "ok" : "loading",
    data: (cached(settings, key) as T) || null,
  }));
  useEffect(() => {
    let active = true;
    if (!path) return;
    const previous = cached(settings, key);
    if (previous !== undefined) {
      setState({ key, status: "ok", data: previous as T });
      return;
    }
    const settled = beginReadingLoad();
    setState({ key, status: "loading", data: null });
    void load<T>(settings, path)
      .then((result) => {
        if (active)
          setState({
            key,
            status: result.status,
            data: result.status === "ok" ? result.data : null,
          });
      })
      .finally(settled);
    return () => {
      active = false;
      settled();
    };
  }, [key, revision]);
  return {
    ...(state.key === key
      ? state
      : { key, status: "loading" as const, data: null }),
    revision,
    reload: () => {
      cache.delete(key);
      setRevision((n) => n + 1);
    },
  };
}
export function usePages<T>(settings: Settings, path: string, pages: number) {
  const key = `${keyFor(settings, path)}|pages=${pages}`;
  type State = {
    key: string;
    status: "loading" | "ok" | "error" | "not-found";
    items: T[];
    nextCursor: string | null;
  };
  const [revision, setRevision] = useState(0);
  const [state, setState] = useState<State>(
    () =>
      (cached(settings, key) as State) || {
        key,
        status: "loading",
        items: [],
        nextCursor: null,
      },
  );
  useEffect(() => {
    let active = true;
    if (cached(settings, key) !== undefined) {
      setState(cached(settings, key) as State);
      return;
    }
    const settled = beginReadingLoad();
    setState({ key, status: "loading", items: [], nextCursor: null });
    void (async () => {
      const items: T[] = [];
      let cursor: string | null = null;
      const cursors = new Set<string>();
      for (let index = 0; index < pages; index++) {
        const url: string =
          path + (cursor ? `&cursor=${encodeURIComponent(cursor)}` : "");
        const result: Result<{ items: T[]; nextCursor: string | null }> =
          await load<{ items: T[]; nextCursor: string | null }>(settings, url);
        if (!active) return;
        if (result.status !== "ok") {
          setState({ key, status: result.status, items, nextCursor: cursor });
          return;
        }
        if (
          result.data.nextCursor &&
          (result.data.nextCursor === cursor ||
            cursors.has(result.data.nextCursor))
        ) {
          setState({ key, status: "error", items, nextCursor: cursor });
          return;
        }
        if (cursor) cursors.add(cursor);
        items.push(...result.data.items);
        cursor = result.data.nextCursor;
        if (!cursor) break;
      }
      const next: State = { key, status: "ok", items, nextCursor: cursor };
      remember(settings, key, next);
      setState(next);
    })().finally(settled);
    return () => {
      active = false;
      settled();
    };
  }, [key, revision]);
  return {
    ...(state.key === key
      ? state
      : { key, status: "loading" as const, items: [], nextCursor: null }),
    partial:
      state.key === key &&
      state.items.length > 0 &&
      !["loading", "ok"].includes(state.status),
    reload: () => {
      for (const k of cache.keys())
        if (k.startsWith(keyFor(settings, path))) cache.delete(k);
      setRevision((n) => n + 1);
    },
  };
}
