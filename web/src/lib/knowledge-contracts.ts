import type { Activity } from "./contracts";

export type ReviewDecision = "pending" | "approved" | "rejected";
export interface Mention {
  id: string;
  surface: string;
  start: number;
  end: number;
  personId: string | null;
  candidatePersonIds?: string[];
  decision: ReviewDecision;
}
export interface DocumentSegment { id: string; text: string; locator: string; mentions: Mention[]; }
export interface KnowledgeDocument {
  id: string; version: string; sourceKey: string; recordKey: string; sourceUrl: string;
  title: string; format: string; bodyStatus: string; licenseStatus: string;
  publishedAt: string | null; collectedAt: string; extractionVersion: string;
  datePrecision?: "date" | "second" | "unknown"; segments: DocumentSegment[];
}
export interface KnowledgeEvidence {
  id: string; documentId: string; documentVersion: string; extractionVersion: string;
  segmentId: string; start: number; end: number; excerpt: string; before: string;
  after: string; mentions: Mention[]; sourceUrl: string; title: string; locator?: string;
}
export interface KnowledgeRelation {
  id: string; subjectId: string; objectId: string; type: string;
  evidenceIds: string[]; decision: "approved"; reason: string;
}
export interface Participant {
  personId: string; name: string; role: string; evidenceIds: string[];
  organizationAtTime: string | null; positionAtTime: string | null;
}
export interface PublicContext {
  eventId: string; eventVersion: string; changeKind: string; activity: Activity;
  scheduledAt?: string | null;
  scheduledPrecision?: "date" | "second" | "unknown" | null;
  participants: Participant[]; relations: KnowledgeRelation[];
  evidence: KnowledgeEvidence[]; documents: KnowledgeDocument[];
}
export interface PersonProfile {
  id: string; name: string; kind: string;
  facts: { label: string; value: string; evidenceIds: string[] }[];
  tenures: {
    organizationId: string; organizationName?: string; position: string; party: string | null;
    validFrom: string | null; validUntil: string | null; observedAt: string; evidenceIds: string[];
  }[];
  relatedIssues: { id: string; title: string }[];
  activities: PublicContext[];
}
export interface BillLineage { id: string; items: KnowledgeRelation[]; }
export interface IssueTimeline { id: string; items: PublicContext[]; nextCursor?: string | null; }
