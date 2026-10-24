"""Distinguish source contents from republishing notices and unavailable bodies."""

import re

from parliament_worker.models import SourceDocument

REPUBLICATION = re.compile(
    r"이\s*자료는.{0,300}?보도자료를\s*전재하여\s*제공함을\s*알려드립니다\s*[.。]?"
)
WRAPPING = " \t\r\n“”\"'‘’「」[](){}<>.,;:。"


def classify_body(text: str) -> str:
    """Classify exact source text without treating a title or iframe as its body."""
    normalized = " ".join(text.split())
    if not normalized.strip(WRAPPING):
        return "unavailable"
    without_notice = REPUBLICATION.sub("", normalized)
    return "available" if without_notice.strip(WRAPPING) else "disclaimer_only"


def document_body_status(document: SourceDocument) -> str:
    """Apply parser status and independently reject raw notice-only protocol inputs."""
    if document.body_status != "available":
        return document.body_status
    return classify_body(document.body)


def require_summary_body(document: SourceDocument) -> None:
    """Reject metadata-only sources before estimation, budget reservation or HTTP."""
    if document_body_status(document) != "available":
        raise ValueError("substantive source body unavailable for summary")
