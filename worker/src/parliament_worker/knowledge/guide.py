"""Human review instructions kept separate from the immutable import contract."""

from typing import Any


def review_guide(batch: dict[str, Any], reviewed_filename: str) -> dict[str, Any]:
    """Describe required operator edits without making factual or approval claims.

    Args:
        batch: Candidate data with source text and unapproved name matches.
        reviewed_filename: Relative name of the private editable review copy.

    Returns:
        A sidecar checklist; it is not accepted as a backend import payload.
    """
    candidates = []
    for document in batch["documents"]:
        for segment in document["segments"]:
            for mention in segment["mentions"]:
                candidates.append(
                    {
                        "documentId": document["id"],
                        "documentVersion": document["version"],
                        "segmentId": segment["id"],
                        "mentionId": mention["id"],
                        "surface": mention["surface"],
                        "candidatePersonIds": mention["candidatePersonIds"],
                        "identityDecision": "pending",
                        "roleDecision": "pending",
                    }
                )
    return {
        "candidateBatchId": batch["id"],
        "reviewedBatchPath": reviewed_filename,
        "publicationApprovalPerformed": False,
        "fieldsToReview": {
            "mentions": "각 이름의 신원을 원문과 공식 인물 자료로 확인한다. 확정 시 personId와 decision=approved를 입력한다. 이름이 같다는 이유로 합치지 않는다. 미확인은 pending, 오탐은 rejected로 남긴다.",
            "relations": "행동 역할을 따로 확인한다. 근거 evidenceIds와 판정 reason을 갖춘 관계만 approved로 추가한다. 단순 언급은 관계·참여자·알림으로 추가하지 않는다. 대표발의/공동발의/예정참여/기관발표/원안-대안 통합을 구분한다.",
            "entities": "인물 facts와 tenures는 근거 evidenceIds를 붙여 입력한다. 직위 기간이 미확인이면 validFrom/validUntil=null로 유지하고 해당 사건 당시 자격만 기록한다. 외부 ID 연결도 검증한다.",
            "activities": "기존 Activity 형식의 사건 초안을 입력한다. summary는 초기 null. 날짜·단계·개별표결을 추정하지 않는다. 예정일과 실제 발생일, 사업 시작과 법령 시행을 구분한다. 최초 입력 version은 검토 초안이며 서버 응답의 파생 버전을 사용한다.",
            "contexts": "eventId/eventVersion마다 relationIds/evidenceIds/documentIds를 묶는다. 변화 종류를 new_record,state_changed,important_correction,explanation_only,extraction_only 중 선택한다. 설명/추출만 변경된 기록은 알림에서 제외된다.",
            "licenses": "본문·발췌 재이용 조건을 문서별로 확인한다. 출처를 근거로 allowed/restricted/unknown을 판정하고 unknown은 공개하지 않는다. PDF 본문의 권한을 HTML 링크의 권한으로 추정하지 않는다.",
        },
        "identityAndRoleCandidates": candidates,
        "relationTemplate": {
            "id": "operator_relation_id",
            "subjectId": "verified_subject_id",
            "objectId": "verified_object_id",
            "type": "lead_sponsor",
            "evidenceIds": ["exact_evidence_id"],
            "decision": "pending",
            "reason": "운영자의 근거 확인 이유를 입력",
        },
        "contextTemplate": {
            "eventId": "existing_activity_id",
            "eventVersion": "draft_activity_version",
            "relationIds": [],
            "evidenceIds": [],
            "documentIds": [],
            "changeKind": "new_record",
            "scheduledAt": None,
            "scheduledPrecision": "unknown",
        },
        "workflow": [
            "이 파일은 안내용이다. reviewedBatchPath의 자료 묶음 복사본을 사람이 검토·편집한다.",
            "pilot validate --batch REVIEW_FILE --output SEALED_FILE로 참조·범위를 검증하고 변경 내용에 맞는 새 batch ID를 만든다.",
            "pilot import --batch SEALED_FILE --import는 인증된 관리 API에 후보 초안을 적재할 뿐 공개하지 않는다.",
            "별도의 관리 API 검수 승인을 직접 수행한다. 자동화된 후보 검사를 실제 사람의 검수나 공개 승인으로 기록하지 않는다.",
        ],
    }
