import type { ApiResult, Bill } from "./contracts";
import type { KnowledgeRelation } from "./knowledge-contracts";
import { getBill } from "./server-api";
import { isEntityId } from "./knowledge-validation";

export type BillSummaryResult = ApiResult<Pick<Bill, "title" | "stage">>;
export async function loadRelatedBillSummaries(
  billId: string,
  items: KnowledgeRelation[],
  lookup: (id: string) => Promise<ApiResult<Pick<Bill, "title" | "stage">>> = getBill
): Promise<Record<string, BillSummaryResult>> {
  const targetIds = [...new Set(items
    .filter(item => item.decision === "approved" && item.type === "incorporated_into_alternative" && (item.subjectId === billId || item.objectId === billId))
    .map(item => item.subjectId === billId ? item.objectId : item.subjectId)
    .filter(isEntityId))].slice(0, 20);
  const summaries: Record<string, BillSummaryResult> = {};
  for (let offset = 0; offset < targetIds.length; offset += 4) {
    await Promise.all(targetIds.slice(offset, offset + 4).map(async id => {
      try {
        const result = await lookup(id);
        summaries[id] = result.status === "ok" ? { status: "ok", data: { title: result.data.title, stage: result.data.stage } } : result;
      } catch { summaries[id] = { status: "offline" }; }
    }));
  }
  return summaries;
}
