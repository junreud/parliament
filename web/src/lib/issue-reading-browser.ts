import { issueReadingPath, issueReadingResponse, type IssueReadingResult } from "./issue-reading";

export async function readBrowserIssueReading(id: string, fetcher: typeof fetch = fetch): Promise<IssueReadingResult> {
  const path = issueReadingPath(id);
  if (!path) return { status: "invalid" };
  try {
    const response = await fetcher(path, { method: "GET", credentials: "omit", redirect: "error", cache: "no-store", signal: AbortSignal.timeout(10000), headers: { Accept: "application/json" } });
    return issueReadingResponse(id, response.status, response.status === 200 ? await response.json() : undefined);
  } catch { return { status: "error" }; }
}
