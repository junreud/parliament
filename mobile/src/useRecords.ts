import { useEffect, useRef, useState } from "react";
import type { Activity, Page } from "../../web/src/lib/contracts";
import { readRecords } from "./api";
import { PREVIEW_RECORDS } from "./preview";
import type { Settings } from "./state";
import { beginReadingLoad } from "./navigation";
export function useRecords(
  settings: Settings,
  options: {
    topic: string;
    type: string;
    query: string;
    savedOnly: boolean;
    interestsOnly: boolean;
  },
) {
  const [records, setRecords] = useState<Activity[]>([]);
  const [status, setStatus] = useState<
    "loading" | "ok" | "error" | "not-found"
  >("loading");
  const [cursor, setCursor] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);
  const [moreBusy, setMoreBusy] = useState(false);
  const [moreError, setMoreError] = useState(false);
  const generation = useRef(0);
  const key = JSON.stringify([
    settings.mode,
    settings.origin,
    options.topic,
    options.type,
    options.query,
    options.savedOnly,
    options.interestsOnly,
    options.savedOnly ? settings.saved[settings.mode] : [],
    options.interestsOnly ? settings.topics : [],
    revision,
  ]);
  const query = () => {
    const q = new URLSearchParams({ limit: "20" });
    if (options.topic) q.set("topic", options.topic);
    if (options.type) q.set("type", options.type);
    if (options.query) q.set("q", options.query);
    return q;
  };
  const filter = (items: Activity[]) =>
    items.filter(
      (record) =>
        (!options.topic || record.topics.includes(options.topic)) &&
        (!options.type || record.type === options.type) &&
        (!options.query ||
          `${record.title} ${record.summary}`
            .toLowerCase()
            .includes(options.query.toLowerCase())) &&
        (!options.interestsOnly ||
          record.topics.some((t) => settings.topics.includes(t))) &&
        (!options.savedOnly ||
          settings.saved[settings.mode].includes(record.id)),
    );
  useEffect(() => {
    const current = ++generation.current;
    let active = true;
    setStatus("loading");
    setRecords([]);
    setCursor(null);
    setMoreError(false);
    setMoreBusy(false);
    if (settings.mode === "preview") {
      setRecords(filter(PREVIEW_RECORDS));
      setStatus("ok");
      return;
    }
    const settled = beginReadingLoad();
    void (async () => {
      if (options.savedOnly) {
        const ids = settings.saved.live;
        const items: Activity[] = [];
        let failed = false;
        for (let i = 0; i < ids.length; i += 4) {
          const results = await Promise.all(
            ids
              .slice(i, i + 4)
              .map((id) =>
                readRecords<Activity>(
                  settings.origin,
                  `/api/v1/activities/${encodeURIComponent(id)}`,
                ),
              ),
          );
          if (!active || current !== generation.current) return;
          for (const result of results) {
            if (result.status === "ok") items.push(result.data);
            else failed = true;
          }
        }
        setRecords(items);
        setStatus(failed ? "error" : "ok");
        return;
      }
      const result = await readRecords<Page<Activity>>(
        settings.origin,
        `/api/v1/${options.query ? "search" : "activities"}?${query()}`,
      );
      if (!active || current !== generation.current) return;
      if (result.status === "ok") {
        setRecords(
          options.interestsOnly ? filter(result.data.items) : result.data.items,
        );
        setCursor(result.data.nextCursor || null);
        setStatus("ok");
      } else setStatus(result.status);
    })().finally(settled);
    return () => {
      active = false;
      settled();
    };
  }, [key]);
  const loadMore = async () => {
    if (!cursor || moreBusy) return;
    const current = generation.current;
    setMoreBusy(true);
    setMoreError(false);
    const q = query();
    q.set("cursor", cursor);
    const result = await readRecords<Page<Activity>>(
      settings.origin,
      `/api/v1/${options.query ? "search" : "activities"}?${q}`,
    );
    if (current !== generation.current) return;
    if (result.status === "ok") {
      const items = options.interestsOnly
        ? filter(result.data.items)
        : result.data.items;
      setRecords((previous) => [
        ...previous,
        ...items.filter((item) => !previous.some((p) => p.id === item.id)),
      ]);
      setCursor(result.data.nextCursor || null);
    } else setMoreError(true);
    setMoreBusy(false);
  };
  return {
    records: settings.mode === "preview" ? filter(PREVIEW_RECORDS) : records,
    status: settings.mode === "preview" ? ("ok" as const) : status,
    cursor: settings.mode === "preview" ? null : cursor,
    moreBusy,
    moreError,
    loadMore,
    reload: () => setRevision((n) => n + 1),
  };
}
