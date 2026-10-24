"""Conservative editorial gates for claims carried into global reduction."""

import re
from typing import Any

INLINE_PROOF = re.compile(
    r"\((?:근거|원문|인용|quote)\s*[:：]|(?:^|\s)Quote\s*[:：]",
    re.IGNORECASE,
)
SOURCE_ABSENCE = re.compile(
    r"(?:기록|자료|문서|원문|발표).{0,60}"
    r"(?:없|확인되지|확인할 수 없|찾을 수 없|있지 않|언급되지)"
)
PROOF_NEGATION = re.compile(
    r"없|아니|미확인|확인되지|확인할 수 없|부재|찾을 수 없|있지 않|언급되지"
)
OFFICE_ASSERTION = re.compile(
    r"(?:직책|직위).{0,16}(?:보유|맡|역임|재임)"
    r"|(?:보유|맡|역임|재임).{0,16}(?:직책|직위)"
)
ROLE_PROOF = re.compile(
    r"시장|군수|구청장|의원|장관|차관|총리|대통령|위원장|의장|대표|"
    r"청장|처장|국장|비서관|감찰관|기관장|직무대행"
)
RESIDENCE_ASSERTION = re.compile(r"거주|주소|살고 있")
CURRENT_POLICY_WORDING = re.compile(
    r"(?:제도|사업|정책)(?:은|는).{0,160}(?:제도임|제도이다|시행한다|지급한다)"
)
UNATTRIBUTED_POLICY_DEFINITION = re.compile(r"제도(?:임|이다)[.。]?$")
PROPOSAL_ATTRIBUTION = re.compile(
    r"원안|법안|개정안|제안|발의|신설하려|도입하려|추진하려|규정하려"
)
PROPOSAL_ACTION = re.compile(
    r"(?:신설|도입|마련|개정|규정|확대)(?:하고|함|했다|하였다)"
)
ANNOUNCEMENT_ATTRIBUTION = re.compile(
    r"(?:발표|보도자료)(?:에 따르면|에서는|는|문은|문에|를 통해|했다)|"
    r"밝혔|설명했|전했|안내했|공개했"
)
SUSPECT_PAYMENT_RECIPIENT = re.compile(
    r"양육비\s*채무자에게.{0,30}(?:먼저|우선)\s*지급"
)


def editorial_reasons(
    claim: dict[str, Any], source_facet: str | None = None
) -> tuple[str, ...]:
    """Flag wording that cannot safely stand as a source-bound claim.

    Args:
        claim: Model claim with a pinned evidence span.
        source_facet: Verified document category for the pinned evidence.

    Returns:
        Editorial reason codes. An empty tuple is not factual approval.
    """
    text = claim.get("text")
    proof = claim.get("evidence")
    if not isinstance(text, str):
        return ("invalid_claim",)
    quote = proof.get("text") if isinstance(proof, dict) else None
    if not isinstance(quote, str):
        quote = ""
    reasons = []
    if INLINE_PROOF.search(text):
        reasons.append("inline_evidence_in_claim")
    if text.rstrip().endswith("("):
        reasons.append("unfinished_sentence")
    if "예정" in text and "예정" not in quote:
        reasons.append("unproven_future_tense")
    if SOURCE_ABSENCE.search(text) and not PROOF_NEGATION.search(quote):
        reasons.append("unproven_source_absence")
    if OFFICE_ASSERTION.search(text) and not ROLE_PROOF.search(quote):
        reasons.append("unproven_office_claim")
    if RESIDENCE_ASSERTION.search(text) and not RESIDENCE_ASSERTION.search(quote):
        reasons.append("unproven_residence_claim")
    if source_facet == "original_bill":
        if (
            CURRENT_POLICY_WORDING.search(text)
            or UNATTRIBUTED_POLICY_DEFINITION.search(text.rstrip())
            or PROPOSAL_ACTION.search(text)
        ) and not PROPOSAL_ATTRIBUTION.search(text):
            reasons.append("proposal_as_current_fact")
        if SUSPECT_PAYMENT_RECIPIENT.search(text):
            reasons.append("payment_recipient_review")
    if source_facet == "government_followup" and not ANNOUNCEMENT_ATTRIBUTION.search(
        text
    ):
        reasons.append("announcement_as_verified_action")
    return tuple(reasons)
