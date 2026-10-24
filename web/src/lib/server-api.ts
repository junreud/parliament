import { cache } from "react";
import { readApi } from "./api";
import type { Activity, ActivityVersion, Page, ApiResult, Bill, Issue, Person } from "./contracts";
import type { PublicContext, PersonProfile, KnowledgeDocument, KnowledgeEvidence, BillLineage, IssueTimeline } from "./knowledge-contracts";
import { readIssueReading } from "./issue-reading-api";
export const getIssueReading = cache(readIssueReading);
export const getActivity = cache((id: string, version?: string): Promise<ApiResult<Activity>> => readApi(`/api/v1/activities/${encodeURIComponent(id)}${version ? `?version=${encodeURIComponent(version)}` : ""}`));
export const getPerson = cache((id: string): Promise<ApiResult<Person>> => readApi(`/api/v1/people/${encodeURIComponent(id)}`));
export const getBill = cache((id: string): Promise<ApiResult<Bill>> => readApi(`/api/v1/bills/${encodeURIComponent(id)}`));
export const getIssue = cache((id: string): Promise<ApiResult<Issue>> => readApi(`/api/v1/issues/${encodeURIComponent(id)}`));

export const getActivityHistory = cache((id: string): Promise<ApiResult<Page<ActivityVersion>>> => readApi(`/api/v1/activities/${encodeURIComponent(id)}/history`));
export const getPersonProfile = cache((id: string): Promise<ApiResult<PersonProfile>> => readApi(`/api/v1/people/${encodeURIComponent(id)}/profile`));
export const getActivityContext = cache((id: string, version?: string): Promise<ApiResult<PublicContext>> => readApi(`/api/v1/activities/${encodeURIComponent(id)}/context${version ? `?version=${encodeURIComponent(version)}` : ""}`));
export const getDocument = cache((id: string, version?: string, extractionVersion?: string): Promise<ApiResult<KnowledgeDocument>> => {
  const query = new URLSearchParams({ ...(version ? { version } : {}), ...(extractionVersion ? { extractionVersion } : {}) });
  return readApi(`/api/v1/documents/${encodeURIComponent(id)}${query.size ? `?${query}` : ""}`);
});
export const getEvidence = cache((id: string): Promise<ApiResult<KnowledgeEvidence>> => readApi(`/api/v1/evidence/${encodeURIComponent(id)}`));
export const getBillLineage = cache((id: string): Promise<ApiResult<BillLineage>> => readApi(`/api/v1/bills/${encodeURIComponent(id)}/lineage`));
export const getIssueTimeline = cache((id: string, cursor?: string): Promise<ApiResult<IssueTimeline>> => readApi(`/api/v1/issues/${encodeURIComponent(id)}/timeline?${new URLSearchParams({ limit: "20", ...(cursor ? { cursor } : {}) })}`));
