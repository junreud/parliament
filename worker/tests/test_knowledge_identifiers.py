"""Worker preflight and Java identifier namespace contracts agree."""

import json
import re
from pathlib import Path

import pytest
from test_knowledge import manifest

from parliament_worker.knowledge.pipeline import read_manifest, validate_manifest
from parliament_worker.knowledge.review import validate_batch


def packet(namespace, value="external-1"):
    """Return synthetic draft entities without factual government assertions."""
    return {
        "id": "batch-a",
        "issueId": "issue-a",
        "entities": [
            {
                "id": "person-a",
                "kind": "person",
                "name": "합성인",
                "identifiers": [{"namespace": namespace, "value": value}],
                "facts": [],
                "tenures": [],
            }
        ],
        "documents": [],
        "evidence": [],
        "relations": [],
        "activities": [],
        "contexts": [],
    }


@pytest.mark.parametrize(
    "namespace", ["nanet.congress_no", "assembly.bill_number", "", "N" * 65, None]
)
def test_manifest_and_review_reject_namespaces_server_cannot_import(
    namespace, tmp_path
):
    source = manifest()
    source["entities"][0]["identifiers"] = [
        {"namespace": namespace, "value": "external-1"}
    ]
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(source))
    with pytest.raises(ValueError, match="namespace"):
        read_manifest(path)
    with pytest.raises(ValueError, match="namespace"):
        validate_batch(packet(namespace))


@pytest.mark.parametrize(
    "value", ["", " " * 3, "x" * 256, "bad\x00value", None, "😀" * 128]
)
def test_identifier_values_share_server_nonblank_utf16_length_limit(value):
    source = manifest()
    source["entities"][0]["identifiers"] = [
        {"namespace": "NANET_CONGRESS_NO", "value": value}
    ]
    with pytest.raises(ValueError, match="identifier"):
        validate_manifest(source)
    with pytest.raises(ValueError, match="identifier"):
        validate_batch(packet("NANET_CONGRESS_NO", value))


def test_example_and_supported_uppercase_namespaces_pass_preflight():
    path = Path(__file__).parents[1] / "examples" / "knowledge-fixture.json"
    actual = read_manifest(path)
    namespaces = [
        identifier["namespace"]
        for entity in actual["entities"]
        for identifier in entity.get("identifiers", [])
    ]
    assert "NANET_CONGRESS_NO" in namespaces
    assert "ASSEMBLY_BILL_NUMBER" in namespaces
    assert all(re.fullmatch(r"[A-Z0-9_]{1,64}", value) for value in namespaces)
    validate_batch(packet("NANET_CONGRESS_NO"))
