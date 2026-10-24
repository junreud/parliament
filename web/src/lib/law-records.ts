export interface LawEvidence {
  label: string;
  text: string;
  locator: string;
}
export interface Law {
  id: string;
  lawId: string;
  mst: string;
  title: string;
  agency: string | null;
  promulgationNumber: string | null;
  promulgatedDate: string | null;
  effectiveDate: string | null;
  collectedAt: string;
  sourceUrl: string;
  sourceVersion: string;
  extractionVersion: string;
  evidence: LawEvidence[];
}
export interface LawPage {
  items: Law[];
  coverage: string;
  nextCursor: null;
}
function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}
function text(value: unknown, max: number) {
  return (
    typeof value === "string" && value.trim().length > 0 && value.length <= max
  );
}
function date(value: unknown): value is string | null {
  if (value === null) return true;
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value))
    return false;
  const parsed = new Date(value + "T00:00:00Z");
  return (
    !Number.isNaN(parsed.getTime()) &&
    parsed.toISOString().slice(0, 10) === value
  );
}
export function lawSource(law: Pick<Law, "mst" | "sourceUrl">): string | null {
  if (!/^[0-9]{1,12}$/.test(law.mst)) return null;
  const expected = `https://www.law.go.kr/LSW/lsInfoP.do?lsiSeq=${law.mst}`;
  return law.sourceUrl === expected ? expected : null;
}
function isLaw(value: unknown): value is Law {
  if (
    !record(value) ||
    typeof value.lawId !== "string" ||
    typeof value.mst !== "string"
  )
    return false;
  return (
    /^[0-9]{1,12}$/.test(value.lawId) &&
    /^[0-9]{1,12}$/.test(value.mst) &&
    value.id === `law_${value.lawId}_${value.mst}` &&
    text(value.title, 500) &&
    (value.agency === null || text(value.agency, 500)) &&
    (value.promulgationNumber === null ||
      text(value.promulgationNumber, 100)) &&
    date(value.promulgatedDate) &&
    date(value.effectiveDate) &&
    typeof value.collectedAt === "string" &&
    /^\d{4}-\d{2}-\d{2}T/.test(value.collectedAt) &&
    !Number.isNaN(Date.parse(value.collectedAt)) &&
    typeof value.sourceVersion === "string" &&
    /^[a-f0-9]{64}$/.test(value.sourceVersion) &&
    typeof value.extractionVersion === "string" &&
    /^[A-Za-z0-9_-]{1,128}$/.test(value.extractionVersion) &&
    typeof value.sourceUrl === "string" &&
    Boolean(lawSource(value as unknown as Law)) &&
    Array.isArray(value.evidence) &&
    value.evidence.length > 0 &&
    value.evidence.length <= 6 &&
    value.evidence.every(
      (item: unknown) =>
        record(item) &&
        text(item.label, 100) &&
        text(item.text, 500) &&
        typeof item.locator === "string" &&
        /^json:법령\.기본정보\.(법령명_한글|법령ID|공포일자|시행일자|공포번호|소관부처\.content)$/.test(
          item.locator,
        ),
    )
  );
}
export function isLawPage(value: unknown): value is LawPage {
  return (
    record(value) &&
    text(value.coverage, 2000) &&
    value.nextCursor === null &&
    Array.isArray(value.items) &&
    value.items.length <= 50 &&
    value.items.every(isLaw) &&
    new Set(value.items.map((item) => item.id)).size === value.items.length
  );
}
