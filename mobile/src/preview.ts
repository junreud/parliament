import type { Activity } from "../../web/src/lib/contracts";
// Isolated visual samples, never a replacement for a failed public API response.
export const PREVIEW_RECORDS: Activity[] = [
  {
    id: "sample-care",
    type: "announcement",
    title: "양육과 돌봄, 정책의 흐름을 살펴보세요",
    summary:
      "정책이 발표된 뒤 어떤 단계를 거치는지, 관련 기록을 한곳에서 읽는 화면의 예시예요.",
    stage: "announced",
    topics: ["family"],
  },
  {
    id: "sample-housing",
    type: "bill",
    title: "주거를 바꾸는 법안, 지금은 어떤 단계일까요?",
    summary:
      "법안의 발의와 심사, 의결을 구분해서 보여줘요. 통과 여부는 공식 기록으로 확인해요.",
    stage: "reviewing",
    topics: ["housing"],
  },
  {
    id: "sample-labor",
    type: "vote",
    title: "노동 관련 의결과 표결을 함께 읽어요",
    summary:
      "공개된 표결과 확인되지 않은 기록을 구분해요. 개인별 결과를 임의로 추정하지 않아요.",
    stage: "voted",
    topics: ["labor"],
  },
  {
    id: "sample-economy",
    type: "law",
    title: "경제·세금 정책, 시행 시점을 확인해요",
    summary:
      "발표와 실제 시행은 서로 다른 단계예요. 날짜와 근거를 구분하는 화면의 예시예요.",
    stage: "effective",
    topics: ["economy-tax"],
  },
].map((item) => ({
  ...item,
  personIds: [],
  billId: null,
  occurredAt: null,
  publishedAt: "2026-10-08T00:00:00Z",
  collectedAt: "2026-10-08T00:00:00Z",
  sourceUrl: "",
  evidence: [],
  votes: [],
  coverage: "디자인 설명용 예시입니다. 실제 정부·국회 활동 기록이 아닙니다.",
  corrected: false,
  version: "preview-1",
}));
