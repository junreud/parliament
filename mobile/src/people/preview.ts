import type {
  PersonProfile,
  PublicContext,
  KnowledgeEvidence,
  Mention,
} from "../../../web/src/lib/knowledge-contracts";
import type {
  PeopleDirectory,
  KnowledgeGraph,
} from "../../../web/src/lib/graph-contracts";
import { PREVIEW_RECORDS } from "../preview";

// Deliberately fictional, isolated from live requests and never assigned official source links.
export const SAMPLE_PEOPLE = [
  {
    id: "sample-haneul",
    name: "김하늘",
    position: "의원 역할 예시",
    organizationName: "가상 의회",
    organizationId: "sample-council",
    kind: "person",
    observedAt: "2026-10-01T00:00:00Z",
  },
  {
    id: "sample-seojun",
    name: "이서준",
    position: "위원 역할 예시",
    organizationName: "가상 위원회",
    organizationId: "sample-committee",
    kind: "person",
    observedAt: "2026-10-01T00:00:00Z",
  },
];
export const SAMPLE_PARAGRAPHS = [
  "정책을 이해할 때는 발표된 계획과 실제 진행된 일을 나누어 읽어요. 이 글은 인물 연결과 읽던 위치 복귀를 확인하기 위한 합성 예시입니다.",
  "먼저 문서의 날짜와 출처를 살펴봐요. 같은 정책을 다루더라도 발의, 심사, 표결은 서로 다른 사건이에요. 각 단계는 별도로 확인할 수 있어야 해요.",
  "기록 속 직위는 당시의 소속과 함께 읽어요. 예전에 맡았던 직책을 현재 직책처럼 표시하거나, 이름이 같은 사람을 자동으로 합치지 않아요.",
  "관심 있는 사람의 이름을 누르면 짧은 소개를 먼저 볼 수 있어요. 창을 닫으면 바로 이 문단으로 돌아와 계속 읽을 수 있어요.",
  "김하늘은 정책을 설명하는 가상 인물이고, 이서준은 연결 탐색을 보여주는 또 다른 가상 인물이에요. 두 사람은 실제 정치 활동을 나타내지 않아요.",
  "전체 인물 문서에서는 시간순 기록이나 주제별 항목을 살펴볼 수 있어요. 다른 사람으로 이동한 뒤 뒤로가기를 눌러도 읽던 위치와 선택한 조건은 유지돼요.",
  "자료가 없다는 이유만으로 활동하지 않았다고 해석하지 않아요. 어떤 기간과 출처를 확인했는지, 아직 확인하지 못한 것은 무엇인지 함께 표시해요.",
  "실제 공개 기록에서는 원문 발췌와 버전을 고정해 근거를 연결해요. 현재 화면은 UX 검증용 예시이므로 공식 근거 링크를 만들지 않아요.",
];
export function sampleMentions(text: string): Mention[] {
  return SAMPLE_PEOPLE.flatMap((person) => {
    const index = Array.from(text).join("").indexOf(person.name);
    if (index < 0) return [];
    const start = Array.from(text.slice(0, index)).length;
    return [
      {
        id: `mention-${person.id}`,
        surface: person.name,
        start,
        end: start + Array.from(person.name).length,
        personId: person.id,
        decision: "approved" as const,
      },
    ];
  });
}
const records: PublicContext[] = [
  "2024-02-12",
  "2024-09-19",
  "2025-03-04",
  "2025-10-21",
  "2026-04-08",
  "2026-09-11",
].map((day, i) => {
  const role = i % 2 === 0 ? "speaker" : "lead_sponsor";
  const activity = {
    ...PREVIEW_RECORDS[0],
    id: `sample-history-${i}`,
    version: `sample-version-${i}`,
    title:
      role === "speaker"
        ? `돌봄 정책 발언 카드 예시 ${i + 1}`
        : `돌봄 법안 발의 카드 예시 ${i + 1}`,
    type: role === "speaker" ? "speech" : "bill",
    stage: role === "speaker" ? "announced" : "proposed",
    personIds: ["sample-haneul"],
    occurredAt: `${day}T01:00:00Z`,
    publishedAt: `${day}T02:00:00Z`,
  };
  return {
    eventId: activity.id,
    eventVersion: activity.version,
    changeKind: "new_record",
    activity,
    participants: [
      {
        personId: "sample-haneul",
        name: "김하늘",
        role,
        evidenceIds: ["sample-evidence"],
        organizationAtTime: "가상 의회",
        positionAtTime: "의원 역할 예시",
      },
    ],
    relations: [],
    evidence: [],
    documents: [],
  };
});
export function previewResource(path: string): unknown | null {
  const url = new URL(path, "https://preview.invalid"),
    parts = url.pathname.split("/"),
    id = parts[4];
  const person = SAMPLE_PEOPLE.find((p) => p.id === id);
  if (parts[3] === "people" && parts[5] === "profile" && person) {
    return {
      id: person.id,
      name: person.name,
      kind: "person",
      facts: [
        {
          label: "소개",
          value:
            "인물 문서와 시간순 이력을 읽는 방식을 보여주는 가상 인물이에요.",
          evidenceIds: [],
        },
      ],
      tenures: [
        {
          organizationId: person.organizationId,
          organizationName: person.organizationName,
          position: person.position,
          party: null,
          validFrom: "2024-01-01",
          validUntil: null,
          observedAt: person.observedAt,
          evidenceIds: [],
        },
      ],
      relatedIssues: [],
      activities: [],
    } satisfies PersonProfile;
  }
  if (parts[3] === "people" && parts[5] === "timeline" && person) {
    let items =
      id === "sample-haneul"
        ? [...records]
        : [...records.slice(0, 2)].map((context) => ({
            ...context,
            activity: { ...context.activity, personIds: [id] },
            participants: context.participants.map((p) => ({
              ...p,
              personId: id,
              name: person.name,
            })),
          }));
    const role = url.searchParams.get("role"),
      from = url.searchParams.get("from"),
      until = url.searchParams.get("until");
    items = items.filter(
      (c) =>
        (!role || c.participants.some((p) => p.role === role)) &&
        (!from || c.activity.occurredAt!.slice(0, 10) >= from) &&
        (!until || c.activity.occurredAt!.slice(0, 10) <= until),
    );
    if (url.searchParams.get("order") !== "oldest") items.reverse();
    const offset = Number(url.searchParams.get("cursor") || 0);
    return {
      id,
      items: items.slice(offset, offset + 2),
      nextCursor: offset + 2 < items.length ? String(offset + 2) : null,
    };
  }
  if (url.pathname === "/api/v1/knowledge/people") {
    const query = (url.searchParams.get("query") || "").toLowerCase();
    return {
      items: SAMPLE_PEOPLE.filter((p) =>
        `${p.name} ${p.organizationName}`.toLowerCase().includes(query),
      ),
      nextCursor: null,
    } satisfies PeopleDirectory;
  }
  if (url.pathname === "/api/v1/knowledge/graph") {
    const root = url.searchParams.get("rootId");
    if (!SAMPLE_PEOPLE.some((p) => p.id === root)) return null;
    return {
      rootKey: `person:${root}`,
      visibility: "published",
      truncated: false,
      nodes: [
        ...SAMPLE_PEOPLE.map((p) => ({
          key: `person:${p.id}`,
          id: p.id,
          kind: "person" as const,
          label: p.name,
          href: `/people/${p.id}`,
          version: null,
        })),
        {
          key: "activity:sample-care",
          id: "sample-care",
          kind: "activity",
          label: "돌봄 정책 이야기 · UX 예시",
          href: "/activities/sample-care",
          version: null,
        },
      ],
      edges: SAMPLE_PEOPLE.map((p) => ({
        id: `sample-relation-${p.id}`,
        sourceKey: `person:${p.id}`,
        targetKey: "activity:sample-care",
        type: "speaker" as const,
        label: "예시 기록의 발언자",
        evidenceIds: [],
        batchId: "sample-batch",
        reviewedAt: null,
        validFrom: null,
        validUntil: null,
        observedAt: null,
      })),
    } satisfies KnowledgeGraph;
  }
  if (parts[3] === "evidence" && id === "sample-evidence")
    return {
      id,
      documentId: "sample-document",
      documentVersion: "sample-version",
      extractionVersion: "sample-extract",
      segmentId: "sample-segment",
      start: 0,
      end: Array.from(SAMPLE_PARAGRAPHS[4]).length,
      excerpt: SAMPLE_PARAGRAPHS[4],
      before: "",
      after: "",
      mentions: sampleMentions(SAMPLE_PARAGRAPHS[4]),
      sourceUrl: "",
      title: "가상 본문 · UX 예시",
      locator: "문단 5",
    } satisfies KnowledgeEvidence;
  if (parts[3] === "activities" && parts[5] === "context")
    return records.find((context) => context.eventId === id) || null;
  return null;
}
export function sampleRecord(id: string) {
  return (
    records.find((context) => context.eventId === id)?.activity ||
    PREVIEW_RECORDS.find((record) => record.id === id)
  );
}
