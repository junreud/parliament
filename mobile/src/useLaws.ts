import { useEffect, useState } from "react";
import snapshot from "./data/laws.json";
import { isLawPage, readLaws, type LawPage } from "./laws";
import type { Settings } from "./state";
import { beginReadingLoad } from "./navigation";

const collection: LawPage | null = isLawPage(snapshot) ? snapshot : null;
export function useLaws(settings: Settings) {
  const [page, setPage] = useState<LawPage | null>(null);
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
    void readLaws(settings.origin)
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
  return {
    page,
    status,
    live,
    reload: () => setRevision((value) => value + 1),
  };
}
export type LawsState = ReturnType<typeof useLaws>;
