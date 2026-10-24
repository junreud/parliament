import type { Mention } from "../../../web/src/lib/knowledge-contracts";
import {
  isEntityId,
  isKnowledgePayload,
} from "../../../web/src/lib/knowledge-validation";
import { isGraphPayload } from "../../../web/src/lib/graph-validation";
import { hasPublicApproval, isPublicBill, isLineageFor } from "./publication";
import { normalizeOrigin } from "../state";
import { transport, type Result, type Transport } from "../api";

export function approvedMentions(
  text: string,
  mentions: Mention[],
  offset = 0,
): Mention[] {
  const points = Array.from(text);
  const ranges = mentions
    .filter((m) => m.start >= offset && m.end <= offset + points.length)
    .sort((a, b) => a.start - b.start || a.end - b.end);
  if (
    ranges.some(
      (m, i) =>
        !Number.isSafeInteger(m.start) ||
        !Number.isSafeInteger(m.end) ||
        m.end <= m.start ||
        (i > 0 && m.start < ranges[i - 1].end) ||
        points.slice(m.start - offset, m.end - offset).join("") !== m.surface,
    )
  )
    return [];
  return ranges.filter(
    (m) => m.decision === "approved" && isEntityId(m.personId),
  );
}
export async function readKnowledge<T>(
  origin: string,
  path: string,
  request: Transport = transport,
): Promise<Result<T>> {
  const base = normalizeOrigin(origin);
  if (!base || !path.startsWith("/api/v1/") || /[#\\]/.test(path))
    return { status: "error" };
  const url = new URL(path, base);
  const p = url.pathname.split("/");
  const allowed =
    url.origin === base &&
    (/^\/api\/v1\/people\/[A-Za-z0-9_-]{1,128}\/(profile|timeline)$/.test(
      url.pathname,
    ) ||
      /^\/api\/v1\/activities\/[A-Za-z0-9_-]{1,128}\/context$/.test(
        url.pathname,
      ) ||
      /^\/api\/v1\/evidence\/[A-Za-z0-9_-]{1,128}$/.test(url.pathname) ||
      /^\/api\/v1\/bills\/[A-Za-z0-9_-]{1,128}(?:\/lineage)?$/.test(
        url.pathname,
      ) ||
      /^\/api\/v1\/knowledge\/(people|graph)$/.test(url.pathname));
  if (!allowed || path.length > 4000) return { status: "error" };
  try {
    const response = await request(url.href);
    if (response.status === 404) return { status: "not-found" };
    if (
      response.status !== 200 ||
      !hasPublicApproval(response.data) ||
      !(
        (p[3] === "bills" && p.length === 5
          ? isPublicBill(response.data)
          : null) ??
        isGraphPayload(path, response.data) ??
        isKnowledgePayload(path, response.data)
      )
    )
      return { status: "error" };
    const value = response.data as Record<string, unknown>;
    if (
      p[3] === "bills" &&
      (value.id !== p[4] || (p[5] === "lineage" && !isLineageFor(p[4], value)))
    )
      return { status: "error" };
    if (p[3] === "people" && value.id !== p[4]) return { status: "error" };
    if (p[3] === "evidence" && value.id !== p[4]) return { status: "error" };
    if (p[3] === "activities" && value.eventId !== p[4])
      return { status: "error" };
    if (
      p[4] === "graph" &&
      value.rootKey !==
        `${url.searchParams.get("rootKind")}:${url.searchParams.get("rootId")}`
    )
      return { status: "error" };
    return { status: "ok", data: response.data as T };
  } catch {
    return { status: "error" };
  }
}
