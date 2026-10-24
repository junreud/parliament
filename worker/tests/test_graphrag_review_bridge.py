"""Only pinned, exact GraphRAG facts cross into a private review batch."""

from copy import deepcopy

import pytest
from test_graphrag_policy_links import policy_batch

from parliament_worker.graphrag.inputs import sources_from_batch
from parliament_worker.graphrag.review_bridge import merge_review_batch
from parliament_worker.knowledge.review import validate_batch


def _snapshot(batch):
    source = sources_from_batch(batch)[0]
    source["generation"] = 1
    unit = source["payload"]["units"][0]
    text = unit["text"]
    first = dict(unit)
    policy_start = text.index("양육비 선지급제")
    policy_end = policy_start + len("양육비 선지급제")
    second = {
        **unit,
        "start": policy_start,
        "end": policy_end,
        "text": text[policy_start:policy_end],
    }
    graph = {
        "kind": "graph",
        "key": "policy-links",
        "version": "graph-v1",
        "dependency": {
            "sources": [
                {
                    "scope": source["scope"],
                    "fingerprint": source["fingerprint"],
                    "generation": 1,
                }
            ]
        },
        "payload": {
            "public": False,
            "nodes": [
                {"id": "b-a", "kind": "bill", "name": "새 법안"},
                {"id": "policy-advance", "kind": "policy", "name": "양육비 선지급제"},
            ],
            "edges": [
                {
                    "id": "edge-1",
                    "source": "b-a",
                    "target": "policy-advance",
                    "type": "concerns",
                    "decision": "pending",
                    "documentIdentitySupported": True,
                    "evidence": [first],
                },
                {
                    "id": "edge-2",
                    "source": "b-a",
                    "target": "policy-advance",
                    "type": "concerns",
                    "decision": "pending",
                    "documentIdentitySupported": True,
                    "evidence": [second],
                },
            ],
        },
    }
    return {
        "sources": [source],
        "model": None,
        "artifacts": {"graph": [graph], "community": []},
    }


def test_bridge_folds_two_proofs_into_one_pending_policy_relation():
    batch = policy_batch()
    snapshot = _snapshot(batch)

    result = merge_review_batch(batch, snapshot)

    validate_batch(result)
    assert result["id"] != batch["id"]
    assert "issuePolicyId" not in result
    assert len(result["relations"]) == 1
    relation = result["relations"][0]
    assert (relation["subjectId"], relation["type"], relation["objectId"]) == (
        "b-a",
        "concerns",
        "policy-advance",
    )
    assert relation["decision"] == "pending"
    assert len(relation["evidenceIds"]) == 2
    assert {item["id"] for item in result["evidence"]} >= set(relation["evidenceIds"])
    assert result == merge_review_batch(batch, snapshot)
    assert batch["relations"] == []


def test_bridge_rejects_a_quote_that_is_not_in_its_pinned_segment():
    batch = policy_batch()
    snapshot = _snapshot(batch)
    snapshot["artifacts"]["graph"][0]["payload"]["edges"][0]["evidence"][0][
        "text"
    ] = "원문에 없는 내용"

    with pytest.raises(ValueError, match="graph proof"):
        merge_review_batch(batch, snapshot)


def test_bridge_does_not_mix_a_changed_document_with_old_graph():
    batch = policy_batch()
    snapshot = _snapshot(batch)
    changed = deepcopy(batch)
    changed["documents"][0]["title"] = "수정된 제목"

    result = merge_review_batch(changed, snapshot)

    validate_batch(result)
    assert result["relations"] == []


def test_bridge_keeps_existing_relation_and_does_not_approve_it():
    batch = policy_batch()
    batch["relations"].append(
        {
            "id": "relation-existing",
            "subjectId": "b-a",
            "objectId": "policy-advance",
            "type": "concerns",
            "evidenceIds": ["ev-a"],
            "decision": "pending",
            "reason": "운영자 검수 대상",
        }
    )
    snapshot = _snapshot(batch)

    result = merge_review_batch(batch, snapshot)

    validate_batch(result)
    assert result["relations"] == batch["relations"]
