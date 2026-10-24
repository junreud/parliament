import { afterEach, describe, expect, it, vi } from "vitest";
import Home from "@/app/page";
afterEach(() => vi.unstubAllGlobals());
describe("all topic and action filters", () => {
  it("omits blank selections because the backend requires actual filter identifiers", async () => {
    const requests: URL[] = [];
    vi.stubGlobal("fetch", async (input: URL) => { requests.push(input); return Response.json({ items: [], nextCursor: null }); });
    await Home({ searchParams: Promise.resolve({ topic: "", type: "", personId: "", billId: "", cursor: "" }) });
    expect([...requests[0].searchParams.keys()]).toEqual(["limit"]);
  });
});
