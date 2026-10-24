"""Find literal source spellings that differ only by horizontal spacing."""

import re

HORIZONTAL_SPACE = r"[ \t\u00a0]{0,8}"


def same_spelling_ignoring_space(left: str, right: str) -> bool:
    """Compare labels without changing any non-whitespace code point.

    Args:
        left: Exact source spelling.
        right: Canonical name from a source-bound identifier.

    Returns:
        True only when the non-whitespace code points match exactly.
    """
    if any(character.isspace() and character not in " \t\u00a0" for character in left):
        return False
    return "".join(left.split()) == "".join(right.split())


def source_form(text: str, canonical: str) -> str | None:
    """Return one exact horizontal-spacing variant present in a source unit.

    Args:
        text: Immutable source unit.
        canonical: Source-bound entity label.

    Returns:
        An exact source substring, or None when spelling is absent or ambiguous.
    """
    if not canonical or not text:
        return None
    if canonical in text:
        return canonical
    characters = "".join(canonical.split())
    if not characters:
        return None
    pattern = HORIZONTAL_SPACE.join(re.escape(character) for character in characters)
    matches = {match.group() for match in re.finditer(pattern, text)}
    if len(matches) != 1:
        return None
    value = matches.pop()
    return value if same_spelling_ignoring_space(value, canonical) else None
