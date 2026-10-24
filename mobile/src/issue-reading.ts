import {
  issueReadingPath,
  issueReadingResponse,
  type IssueReadingResult,
} from "../../web/src/lib/issue-reading";
import { transport, type Transport } from "./api";
import { normalizeOrigin } from "./state";

export async function readIssueReading(
  origin: string,
  id: string,
  request: Transport = transport,
): Promise<IssueReadingResult> {
  const path = issueReadingPath(id);
  if (!path) return { status: "invalid" };
  const base = normalizeOrigin(origin);
  if (!base) return { status: "error" };
  try {
    const response = await request(new URL(path, base).href);
    return issueReadingResponse(id, response.status, response.data);
  } catch {
    return { status: "error" };
  }
}
