import { useEffect, useState } from "react";
import snapshot from "./data/radar.json";
import { isRadarPage, type RadarPage } from "../../web/src/lib/radar";
import { readRadar } from "./radar";
import type { Settings } from "./state";
import { beginReadingLoad } from "./navigation";
const collection: RadarPage | null = isRadarPage(snapshot) ? snapshot : null;
export function useRadar(settings: Settings) {
  const [page, setPage] = useState<RadarPage | null>(null);
  const [status, setStatus] = useState<
    "loading" | "ok" | "error" | "not-found"
  >("loading");
  const [revision, setRevision] = useState(0);
  const live = settings.mode === "live";
  useEffect(() => {
    let active = true;
    setPage(null);
    setStatus("loading");
    if (!live) {
      setPage(collection);
      setStatus(collection ? "ok" : "error");
      return;
    }
    const settled = beginReadingLoad();
    void readRadar(settings.origin)
      .then((result) => {
        if (!active) return;
        setStatus(result.status);
        if (result.status === "ok") setPage(result.data);
      })
      .finally(settled);
    return () => {
      active = false;
      settled();
    };
  }, [live, settings.origin, revision]);
  return { page, status, live, reload: () => setRevision((x) => x + 1) };
}
export type RadarState = ReturnType<typeof useRadar>;
