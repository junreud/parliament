"""Synthetic inputs verify the selected-source review packet, never public facts."""

import importlib.util
import unittest
from pathlib import Path


class ChildSupportReviewTest(unittest.TestCase):
    def module(self):
        path = Path(__file__).parents[1] / "prepare_child_support_review.py"
        spec = importlib.util.spec_from_file_location("review_packet", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def sample(self):
        return {
            "id": "batch_fixture",
            "issueId": "child-support-advance",
            "entities": [
                {"id": "bill-" + str(number), "kind": "bill", "name": "검증용 안건"}
                for number in (
                    2200703,
                    2200987,
                    2201497,
                    2201227,
                    2201707,
                    2202484,
                    2203287,
                    2203461,
                    2204313,
                )
            ],
            "relations": [],
            "activities": [],
            "contexts": [],
            "documents": [
                {
                    "id": "doc-alternative-2204313-pdf",
                    "version": "fixture",
                    "extractionVersion": "extract_fixture",
                    "segments": [
                        {
                            "id": "segment_fixture",
                            "locator": "pdf:page[1]",
                            "text": "2200703 2200987 2201497 2201227 2201707 2202484 2203287 2203461",
                            "mentions": [],
                        }
                    ],
                }
            ],
            "evidence": [
                {
                    "id": "evidence_fixture",
                    "documentId": "doc-alternative-2204313-pdf",
                    "documentVersion": "fixture",
                    "extractionVersion": "extract_fixture",
                    "segmentId": "segment_fixture",
                    "start": 0,
                    "end": 63,
                }
            ],
        }

    def test_lineage_candidates_remain_pending_and_have_exact_evidence(self):
        result = self.module().enrich(self.sample())
        self.assertEqual(8, len(result["relations"]))
        self.assertTrue(all(r["decision"] == "pending" for r in result["relations"]))
        self.assertTrue(
            all(r["evidenceIds"] == ["evidence_fixture"] for r in result["relations"])
        )
        self.assertEqual([], result["activities"])

    def test_absent_bill_number_is_never_filled_from_expected_list(self):
        batch = self.sample()
        batch["documents"][0]["segments"][0]["text"] = "2201707"
        result = self.module().enrich(batch)
        self.assertEqual(
            ["bill-2201707"], [r["subjectId"] for r in result["relations"]]
        )

    def test_repeated_packet_has_stable_identity_without_mutating_input(self):
        batch = self.sample()
        module = self.module()
        self.assertEqual(module.enrich(batch), module.enrich(batch))
        self.assertEqual([], batch["relations"])

    def test_pilot_policy_identity_is_carried_into_review_packet(self):
        batch = self.sample()
        batch["entities"].append(
            {
                "id": "policy-child-support-advance",
                "kind": "policy",
                "name": "양육비 선지급제",
                "identifiers": [],
                "facts": [],
                "tenures": [],
            }
        )
        result = self.module().enrich(batch)
        self.assertEqual("policy-child-support-advance", result["issuePolicyId"])

    def test_announcement_does_not_invent_a_scheduled_role(self):
        batch = self.sample()
        batch["entities"].append(
            {"id": "person-won-minkyung", "kind": "person", "name": "원민경"}
        )
        document = {
            "id": "doc-child-support-followup",
            "version": "fixture",
            "extractionVersion": "extract_fixture",
            "sourceKey": "official_fixture",
            "recordKey": "fixture",
            "sourceUrl": "https://www.mogef.go.kr/fixture",
            "title": "검증용 발표",
            "bodyStatus": "available",
            "publishedAt": "2026-08-13T00:00:00+09:00",
            "collectedAt": "2026-10-08T00:00:00+09:00",
            "segments": [
                {
                    "id": "segment_release",
                    "text": "원민경 장관 주재로 개최했다.",
                    "locator": "html:p[1]",
                }
            ],
        }
        batch["documents"].append(document)
        batch["evidence"].append(
            {
                "id": "evidence_release",
                "documentId": document["id"],
                "segmentId": "segment_release",
            }
        )
        result = self.module().enrich(batch)
        self.assertEqual("announced", result["activities"][0]["stage"])
        self.assertFalse(
            any(r["type"] == "scheduled_participant" for r in result["relations"])
        )
        document["segments"][0]["text"] = "원민경 장관 주재로 개최한다."
        result = self.module().enrich(batch)
        self.assertEqual("scheduled", result["activities"][0]["stage"])
        self.assertEqual(
            1,
            sum(r["type"] == "scheduled_participant" for r in result["relations"]),
        )
        document["publishedAt"] = None
        self.assertEqual([], self.module().enrich(batch)["activities"])


if __name__ == "__main__":
    unittest.main()
