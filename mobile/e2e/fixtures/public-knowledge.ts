import { PREVIEW_RECORDS } from "../../src/preview";
export const person = {
  id: "p_public",
  name: "공개 연동 검증 인물",
  kind: "person",
  position: "검증 직위",
  organizationId: "org_public",
  organizationName: "검증 기관",
  observedAt: "2026-10-18T00:00:00Z",
};
export const evidence = {
  id: "ev_public",
  documentId: "doc_public",
  documentVersion: "source-v1",
  extractionVersion: "extract-v1",
  segmentId: "seg_public",
  start: 0,
  end: 10,
  excerpt: "공개 연동 검증 인물",
  before: "합성 검증 자료의 앞 문장.",
  after: "원문에서 확인한 범위를 넘어 행동을 추정하지 않습니다.",
  mentions: [
    {
      id: "mention_public",
      surface: "공개 연동 검증 인물",
      start: 0,
      end: 10,
      personId: person.id,
      decision: "approved",
    },
  ],
  sourceUrl: "https://www.assembly.go.kr/fixture-only",
  title: "실제 정치 사건이 아닌 연동 검증용 합성 문서",
  locator: "검증 문단 1",
};
evidence.end = Array.from(evidence.excerpt).length;
evidence.mentions[0].end = evidence.end;
export const activity = {
  ...PREVIEW_RECORDS[0],
  id: "event_public",
  title: "공개된 합성 검증 기록",
  version: "public-v1",
  personIds: [person.id],
  billId: "bill_original",
  sourceUrl: evidence.sourceUrl,
  evidence: [
    {
      id: evidence.id,
      sourceUrl: evidence.sourceUrl,
      sourceVersion: evidence.documentVersion,
      locator: evidence.locator,
      excerpt: evidence.excerpt,
    },
  ],
};
export const context = {
  eventId: activity.id,
  eventVersion: activity.version,
  changeKind: "new_record",
  activity,
  participants: [
    {
      personId: person.id,
      name: person.name,
      role: "speaker",
      evidenceIds: [evidence.id],
      organizationAtTime: "당시 검증 기관",
      positionAtTime: "당시 검증 직위",
    },
  ],
  relations: [],
  evidence: [evidence],
  documents: [],
};
export const profile = {
  id: person.id,
  name: person.name,
  kind: "person",
  facts: [
    {
      label: "확인된 소개",
      value: "합성 검증 자료 v1",
      evidenceIds: [evidence.id],
    },
  ],
  tenures: [
    {
      organizationId: person.organizationId,
      organizationName: person.organizationName,
      position: person.position,
      party: null,
      observedAt: person.observedAt,
      validFrom: "2024-01-01",
      validUntil: "2025-12-31",
      evidenceIds: [evidence.id],
    },
  ],
  activities: [context],
  relatedIssues: [],
};
export const bill = {
  id: "bill_original",
  title: "원안 · 합성 검증 법안",
  stage: "unknown",
  activities: [activity],
  votes: [],
  sourceUrl: evidence.sourceUrl,
};
export const alternative = {
  ...bill,
  id: "bill_alternative",
  title: "대안 · 합성 검증 법안",
  activities: [],
};
export const lineage = {
  id: bill.id,
  items: [
    {
      id: "relation_alternative",
      subjectId: bill.id,
      objectId: alternative.id,
      type: "incorporated_into_alternative",
      decision: "approved",
      evidenceIds: [evidence.id],
      reason: "원안과 대안의 연결을 검증하기 위한 합성 근거입니다.",
    },
  ],
};
export const graph = {
  rootKey: `person:${person.id}`,
  visibility: "published",
  truncated: false,
  nodes: [
    {
      key: `person:${person.id}`,
      id: person.id,
      kind: "person",
      label: person.name,
      href: `/people/${person.id}`,
      version: null,
    },
    {
      key: `bill:${bill.id}`,
      id: bill.id,
      kind: "bill",
      label: bill.title,
      href: `/bills/${bill.id}`,
      version: null,
    },
  ],
  edges: [
    {
      id: "edge_public",
      sourceKey: `person:${person.id}`,
      targetKey: `bill:${bill.id}`,
      type: "lead_sponsor",
      label: "대표발의",
      evidenceIds: [evidence.id],
      batchId: "batch_public",
      reviewedAt: "2026-10-18T00:30:00Z",
      validFrom: null,
      validUntil: null,
      observedAt: person.observedAt,
    },
  ],
};
