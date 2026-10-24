"""Conservative coverage checks for present-tenure answers."""

import re

CURRENT_TENURE_QUESTION = re.compile(
    r"(?:현재|지금).{0,60}재임\s*여부|재임\s*여부.{0,60}(?:현재|지금)"
)
CURRENT_TENURE_RESPONSE = re.compile(
    r"(?:현재|지금).{0,60}(?:재임|현직|직위|확인|판단|알\s*수\s*없)"
    r"|(?:재임|현직).{0,40}(?:현재|지금|여부|확인|판단|알\s*수\s*없)"
)
OBSERVATION_TIME_QUESTION = re.compile(r"관측\s*시점")
OBSERVATION_TIME_RESPONSE = re.compile(
    r"\d{4}(?:[-./년]\s*\d{1,2}){0,2}.{0,20}(?:기준|관측|수집|확인)"
    r"|(?:관측|수집)\s*시점.{0,30}(?:미상|모르|알\s*수\s*없|확인할\s*수\s*없|제시되지)"
)
AFFIRMATIVE_PRESENT_TENURE = re.compile(
    r"(?:현재|지금).{0,40}(?:재임\s*중|현직|맡고\s*있|재직\s*중)"
    r"|(?:재임\s*중|현직|재직\s*중).{0,40}(?:현재|지금)"
)
UNCERTAIN_TENURE = re.compile(
    r"(?:알\s*수\s*없|확인할\s*수\s*없|확인되지|단정할\s*수\s*없)"
)


def answer_coverage_findings(
    question: str, answer: str, *, insufficient: bool = False
) -> list[str]:
    """Find unanswered temporal parts without assuming source recency.

    Args:
        question: Fixed user question.
        answer: Source-bound model prose.
        insufficient: Whether the answer already abstained.

    Returns:
        Conservative reason codes. Passing this check is not factual approval.
    """
    if insufficient:
        return []
    findings: list[str] = []
    current_tenure = bool(CURRENT_TENURE_QUESTION.search(question))
    if current_tenure and not CURRENT_TENURE_RESPONSE.search(answer):
        findings.append("current_tenure_unanswered")
    if OBSERVATION_TIME_QUESTION.search(
        question
    ) and not OBSERVATION_TIME_RESPONSE.search(answer):
        findings.append("observation_time_unanswered")
    if (
        current_tenure
        and AFFIRMATIVE_PRESENT_TENURE.search(answer)
        and not UNCERTAIN_TENURE.search(answer)
    ):
        # Source excerpts do not currently bind a verified observation timestamp.
        findings.append("current_tenure_unverified")
    return findings
