"""Scheduled actions remain separate from actual occurrence in review packets."""

import pytest

from parliament_worker.knowledge.guide import review_guide
from parliament_worker.knowledge.review import validate_batch


def batch(scheduled_at=None, precision="unknown"):
    """Return a synthetic pending context; no government action is asserted."""
    return {
        "id": "batch-a",
        "issueId": "issue-a",
        "entities": [],
        "documents": [],
        "evidence": [],
        "relations": [],
        "activities": [{"id": "event-a", "version": "version-a"}],
        "contexts": [
            {
                "eventId": "event-a",
                "eventVersion": "version-a",
                "relationIds": [],
                "evidenceIds": [],
                "documentIds": [],
                "changeKind": "new_record",
                "scheduledAt": scheduled_at,
                "scheduledPrecision": precision,
            }
        ],
    }


@pytest.mark.parametrize(
    "value",
    ["invalid", "2024-13-01T00:00:00+09:00", "2024-01-01", "2024-01-01T00:00:00"],
)
def test_scheduled_time_requires_a_valid_iso_time_with_timezone(value):
    with pytest.raises(ValueError, match="scheduled"):
        validate_batch(batch(value, "date"))


def test_scheduled_precision_is_bounded_and_unknown_is_not_an_occurrence():
    with pytest.raises(ValueError, match="scheduled"):
        validate_batch(batch(None, "minute"))
    validate_batch(batch())
    validate_batch(batch("2024-01-01T00:00:00+09:00", "date"))
    guide = review_guide(batch(), "review.json")
    assert guide["contextTemplate"]["scheduledAt"] is None
    assert guide["contextTemplate"]["scheduledPrecision"] == "unknown"
