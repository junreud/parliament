"""Keep contact fields out of new question requests to the remote model."""

import re

CONTACT_IN_SOURCE = re.compile(
    r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}"
    r"|(?<!\d)(?:\(?0\d{1,2}\)?[\s.)-]?)\d{3,4}[\s.-]\d{4}(?!\d)"
    r"|(?<!\d)01\d{8,9}(?!\d)"
    r"|(?<!\d)1[568]\d{2}[\s.-]?\d{4}(?!\d)"
    r"|(?:직장주소|주소)\s*[:：]"
    r"|(?:\(\s*우편\s*\)|우편\s*[:：])\s*"
    r"[가-힣]{2,}(?:특별자치시|특별자치도|특별시|광역시|도)\s+[가-힣0-9]"
)
CONTACT_LABEL_SUFFIX = re.compile(
    r"(?:연락처|전화번호|전화|휴대전화|휴대폰|팩스|Fax|Tel|직장주소|주소)\s*[:：]?\s*$",
    re.IGNORECASE,
)


def contains_contact(text: str) -> bool:
    """Detect contact or labeled address text in a source evidence span."""
    return bool(CONTACT_IN_SOURCE.search(text))


def contact_free_prefix(text: str) -> str:
    """Return only the exact source prefix before its first contact field."""
    match = CONTACT_IN_SOURCE.search(text)
    if match is None:
        return text
    prefix = CONTACT_LABEL_SUFFIX.sub("", text[: match.start()]).rstrip()
    return prefix if not contains_contact(prefix) else ""


def safe_context_text(text: str) -> str:
    """Omit a report label if it contains a contact field."""
    return "" if contains_contact(text) else text
