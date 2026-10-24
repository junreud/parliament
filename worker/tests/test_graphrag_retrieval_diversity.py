"""Evidence diversity regressions for questions spanning official documents."""

from copy import deepcopy

from test_graphrag_engine import make_factory

from parliament_worker.graphrag.inputs import fingerprint
from parliament_worker.graphrag.query import _local_context
from parliament_worker.graphrag.store import GraphStore


def test_comparison_question_includes_bill_and_followup_source(tmp_path):
    """An explicit comparison cannot spend every proof slot on one bill."""
    factory, source = make_factory(tmp_path)
    changed = deepcopy(source)
    template = changed["payload"]["units"][0]
    bills = [
        {
            **template,
            "id": f"bill-{index}",
            "documentId": "doc-bill-2204313",
            "text": (
                "위원회 대안 2204313은 양육비 선지급 제도와 채무자에 대한 "
                f"회수 절차 {index}를 제안한다."
            ),
        }
        for index in range(8)
    ]
    followup = [
        {
            **template,
            "id": f"followup-{index}",
            "documentId": "doc-government-followup",
            "text": (
                "정부는 양육비 선지급금 회수 현황을 공유하고 "
                f"제도 개선 사항 {index}을 논의할 예정이라고 발표했다."
            ),
        }
        for index in range(2)
    ]
    changed["payload"]["units"] = bills + followup
    changed["fingerprint"] = fingerprint(changed["payload"])
    factory.store.put_sources([changed])

    selected, _, _ = _local_context(
        factory.store,
        "법안 2204313과 정부 발표는 양육비 선지급제에 관해 각각 무엇을 말하나요?",
    )
    assert {proof["documentId"] for proof in selected} == {
        "doc-bill-2204313",
        "doc-government-followup",
    }


def test_scoped_comparison_keeps_each_named_organization_rule(tmp_path):
    """Generic chair wording still belongs to its explicit graph endpoint."""
    store = GraphStore(tmp_path / "state")

    def proof(identifier: str, text: str) -> dict[str, str]:
        return {
            "id": identifier,
            "documentId": "doc-" + identifier,
            "sourceUrl": "https://www.example.go.kr/" + identifier,
            "text": text,
        }

    president = proof("president", "김가 대통령이라는 공식 브리핑 표기")
    economic = proof("economic", "위원구성 : 대통령(의장), 부의장, 당연직위원")
    science = proof("science", "국가과학기술자문회의는 대통령(의장) 및 부의장으로 구성")
    edges = [
        {
            "id": "economic",
            "source": "p-a",
            "target": "org-economic",
            "type": "holds_office",
            "decision": "pending",
            "evidence": [president, economic],
        },
        {
            "id": "science",
            "source": "p-a",
            "target": "org-science",
            "type": "holds_office",
            "decision": "pending",
            "evidence": [president, science],
        },
    ]
    edges.extend(
        {
            "id": f"noise-{index}",
            "source": "p-a",
            "target": "org-other",
            "type": "holds_office",
            "decision": "pending",
            "evidence": [
                proof(
                    f"noise-{index}",
                    "김가 대통령과 국민경제자문회의 및 국가과학기술자문회의 관련 안내 자료",
                )
            ],
        }
        for index in range(8)
    )
    snapshot = {
        "graphs": [
            {
                "payload": {
                    "nodes": [
                        {"id": "p-a", "kind": "person", "name": "김가"},
                        {
                            "id": "org-economic",
                            "kind": "organization",
                            "name": "국민경제자문회의",
                        },
                        {
                            "id": "org-science",
                            "kind": "organization",
                            "name": "국가과학기술자문회의",
                        },
                        {"id": "org-other", "kind": "organization", "name": "기타기관"},
                    ],
                    "edges": edges,
                }
            }
        ],
        "reports": [],
        "sources": [],
    }

    selected, context, _ = _local_context(
        store,
        "김가 대통령은 국민경제자문회의와 국가과학기술자문회의에서 각각 어떤 역할인가?",
        entity_id="p-a",
        index_snapshot=snapshot,
    )

    assert context == []  # Pending relation prose is never promoted.
    assert {"doc-economic", "doc-science"} <= {item["documentId"] for item in selected}
