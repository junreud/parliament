import { describe, expect, it, vi } from "vitest";
import sample from "./fixtures/issue-reading-v1-success.json";
import { readBrowserIssueReading } from "@/lib/issue-reading-browser";
describe("same-origin browser reading", () => {
  it("requests only the public relative path without credentials or a persistent cache", async () => {
    const fetcher = vi.fn(async () => Response.json(sample));
    expect((await readBrowserIssueReading("test-issue", fetcher)).status).toBe("ok");
    expect(fetcher.mock.calls[0]).toEqual(["/api/v1/issues/test-issue/reading", expect.objectContaining({ credentials: "omit", cache: "no-store", method: "GET", redirect: "error" })]);
    expect(await readBrowserIssueReading("../admin", fetcher)).toEqual({ status: "invalid" });
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
  it.each([[404, "not-found"], [409, "conflict"], [503, "error"]] as const)("keeps %s distinct and never substitutes a dossier", async (status, expected) => {
    expect(await readBrowserIssueReading("test-issue", async () => Response.json(sample, { status }))).toEqual({ status: expected });
  });
  it("rejects an unfinished or damaged 200", async () => {
    for (const data of [{ ...sample, publicationState: "pending" }, {}])
      expect(await readBrowserIssueReading("test-issue", async () => Response.json(data))).toEqual({ status: "error" });
  });
});
