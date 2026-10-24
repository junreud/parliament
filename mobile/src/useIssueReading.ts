import { useEffect, useState } from "react";
import type { IssueReadingResult } from "../../web/src/lib/issue-reading";
import { readIssueReading } from "./issue-reading";
import { beginReadingLoad } from "./navigation";
import type { Settings } from "./state";

type State = IssueReadingResult | { status: "loading" | "unconfigured" };
export function useIssueReading(settings: Settings, id: string) {
  const key = `${settings.mode}|${settings.origin}|${id}`;
  const [revision, setRevision] = useState(0);
  const [state, setState] = useState<{ key: string; result: State }>({
    key,
    result: { status: settings.mode === "live" ? "loading" : "unconfigured" },
  });
  useEffect(() => {
    let active = true;
    if (settings.mode !== "live") {
      setState({ key, result: { status: "unconfigured" } });
      return;
    }
    const settled = beginReadingLoad();
    setState({ key, result: { status: "loading" } });
    void readIssueReading(settings.origin, id)
      .then((result) => {
        if (active) setState({ key, result });
      })
      .finally(settled);
    return () => {
      active = false;
      settled();
    };
  }, [key, revision]);
  return {
    result: state.key === key ? state.result : { status: "loading" as const },
    reload: () => setRevision((value) => value + 1),
  };
}
