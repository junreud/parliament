"""Conservative quality checks for prose derived from fixed source quotes."""

import re

INTERNAL_ALIAS = re.compile(r"(?<![A-Za-z0-9])(?:E|N)\d+(?![A-Za-z0-9])")
INTERNAL_GRAPH_ID = re.compile(
    r"(?<![A-Za-z0-9_])[A-Za-z][A-Za-z0-9]{0,24}_[0-9a-f]{32,}(?![0-9a-f])"
)
SCHEDULED_ACTION = re.compile(
    r"개최한다|개최할 예정|개최 예정|열릴 예정|" r"주재할 예정|참석할 예정|진행할 예정"
)
COMPLETED_ACTION = re.compile(
    r"개최했다|개최함|주재했다|주재함|" r"참석했다|참석함|진행했다|진행함"
)


def claim_quality_flags(text: str, quote: str) -> list[str]:
    """Flag internal aliases and a narrow scheduled-to-completed tense shift.

    Args:
        text: The model's factual claim.
        quote: The exact cited source interval.

    Returns:
        Review flags. These are candidates, not factual judgments.
    """
    flags = []
    if INTERNAL_ALIAS.search(text):
        flags.append("internal_member_alias")
    if INTERNAL_GRAPH_ID.search(text):
        flags.append("internal_graph_id")
    if SCHEDULED_ACTION.search(quote) and COMPLETED_ACTION.search(text):
        flags.append("scheduled_source_rendered_completed")
    return flags
