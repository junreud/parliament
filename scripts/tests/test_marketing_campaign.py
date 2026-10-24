"""Meaningful cohort, readiness, budget and operational deadline regressions."""

import csv
import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from marketing.campaign import (
    budget_summary,
    check,
    deadline_state,
    public_https,
    report,
    validate_board,
)
from marketing.metrics import (
    aggregate_events,
    merge_external_report,
    normalize_backend_report,
)


def event(person, cohort, timestamp, name, context="organic"):
    """Build a minimal consented, topic-free research event."""
    return {
        "participant_id": person,
        "cohort": cohort,
        "consented_at": "2026-10-17T12:00:00+09:00",
        "event_at": timestamp,
        "event": name,
        "visit_context": context,
    }


class CohortTest(unittest.TestCase):
    """Prevent short observations and interview visits becoming retention claims."""

    def test_d7_needs_full_168_hours_and_later_local_day(self):
        rows = [
            event("a", "external", "2026-10-18T20:00:00+09:00", "explainer_opened"),
            event("a", "external", "2026-10-18T20:01:00+09:00", "source_opened"),
            event("a", "external", "2026-10-19T10:00:00+09:00", "explainer_opened"),
        ]
        early = aggregate_events(
            rows, datetime.fromisoformat("2026-10-25T20:00:00+09:00")
        )
        self.assertEqual(early["external"]["d7_eligible"], 0)
        self.assertIsNone(early["external"]["d7_organic_rate"])
        mature = aggregate_events(
            rows, datetime.fromisoformat("2026-10-25T20:01:00+09:00")
        )
        self.assertEqual(mature["external"]["d7_eligible"], 1)
        self.assertEqual(mature["external"]["d7_organic_returned"], 1)
        self.assertEqual(mature["external"]["d7_organic_rate"], 1.0)

    def test_friend_external_and_prompted_returns_are_separate(self):
        rows = []
        for person, cohort, context in [
            ("a", "external", "interview"),
            ("b", "friend", "organic"),
        ]:
            rows.extend(
                [
                    event(
                        person, cohort, "2026-10-18T12:01:00+09:00", "explainer_opened"
                    ),
                    event(
                        person, cohort, "2026-10-18T12:02:00+09:00", "timeline_expanded"
                    ),
                    event(
                        person,
                        cohort,
                        "2026-10-20T12:00:00+09:00",
                        "explainer_opened",
                        context,
                    ),
                ]
            )
        result = aggregate_events(
            rows, datetime.fromisoformat("2026-10-26T12:00:00+09:00")
        )
        self.assertEqual(result["external"]["d7_organic_returned"], 0)
        self.assertEqual(result["external"]["d7_prompted_returned"], 1)
        self.assertEqual(result["friend"]["d7_organic_returned"], 1)

    def test_different_visit_contexts_cannot_form_one_activation(self):
        rows = [
            event(
                "a",
                "external",
                "2026-10-18T12:00:00+09:00",
                "explainer_opened",
                "interview",
            ),
            event(
                "a", "external", "2026-10-18T12:01:00+09:00", "source_opened", "organic"
            ),
        ]
        result = aggregate_events(
            rows, datetime.fromisoformat("2026-10-26T12:00:00+09:00")
        )
        self.assertEqual(result["all"]["activated"], 0)

    def test_exact_168_hour_return_is_outside_half_open_window(self):
        rows = [
            event("a", "external", "2026-10-18T12:00:00+09:00", "explainer_opened"),
            event("a", "external", "2026-10-18T12:01:00+09:00", "source_opened"),
            event("a", "external", "2026-10-25T12:01:00+09:00", "explainer_opened"),
        ]
        result = aggregate_events(
            rows, datetime.fromisoformat("2026-10-25T12:01:00+09:00")
        )
        self.assertEqual(result["all"]["d7_eligible"], 1)
        self.assertEqual(result["all"]["d7_organic_returned"], 0)
        self.assertEqual(result["all"]["d7_organic_rate"], 0.0)

    def test_source_before_open_and_same_day_open_do_not_count(self):
        rows = [
            event("a", "external", "2026-10-18T12:01:00+09:00", "source_opened"),
            event("a", "external", "2026-10-18T12:02:00+09:00", "explainer_opened"),
        ]
        result = aggregate_events(
            rows, datetime.fromisoformat("2026-10-26T12:00:00+09:00")
        )
        self.assertEqual(result["external"]["activated"], 0)

    def test_unconsented_future_and_withdrawn_people_are_excluded(self):
        rows = [
            event("a", "external", "2026-10-16T12:00:00+09:00", "explainer_opened"),
            event("b", "external", "2026-10-18T12:00:00+09:00", "explainer_opened"),
            event("b", "external", "2026-10-18T12:01:00+09:00", "source_opened"),
            event("b", "external", "2026-10-19T12:00:00+09:00", "withdrawn"),
            event("c", "external", "2026-11-18T12:00:00+09:00", "explainer_opened"),
        ]
        result = aggregate_events(
            rows, datetime.fromisoformat("2026-10-26T12:00:00+09:00")
        )
        self.assertEqual(result["all"]["enrolled"], 0)

    def test_no_input_is_unknown_instead_of_fake_zero(self):
        result = aggregate_events(
            None, datetime.fromisoformat("2026-10-26T12:00:00+09:00")
        )
        self.assertIsNone(result["all"]["activated"])
        self.assertIsNone(merge_external_report(None)["status"])

    def test_backend_contract_preserves_null_and_measured_zero(self):
        value = {
            "observedAt": "2026-10-23T20:00:00+09:00",
            "calendarZone": "Asia/Seoul",
            "retentionDays": 35,
            "cohorts": [
                {
                    "cohort": "external",
                    "enrolled": 3,
                    "activated": 2,
                    "d7Eligible": 0,
                    "d7Returned": 0,
                    "organicReturned": 0,
                    "researchReturned": 0,
                    "d7Retention": None,
                }
            ],
            "acquisition": {"instagram": 3},
        }
        result = normalize_backend_report(value)
        self.assertEqual(result["cohorts"]["external"]["d7_eligible"], 0)
        self.assertIsNone(result["cohorts"]["external"]["d7_organic_rate"])
        self.assertIsNone(result["cohorts"]["friend"]["enrolled"])
        self.assertEqual(result["acquisition"], {"instagram": 3})

    def test_backend_total_return_rate_is_not_mislabeled_as_organic(self):
        value = {
            "cohorts": [
                {
                    "cohort": "external",
                    "enrolled": 1,
                    "activated": 1,
                    "d7Eligible": 1,
                    "d7Returned": 1,
                    "organicReturned": 0,
                    "researchReturned": 1,
                    "d7Retention": 1.0,
                }
            ]
        }
        cohort = normalize_backend_report(value)["cohorts"]["external"]
        self.assertEqual(cohort["d7_total_rate"], 1.0)
        self.assertEqual(cohort["d7_organic_rate"], 0.0)
        self.assertNotIn("d7_rate", cohort)

    def test_exact_return_window_excludes_after_7_days(self):
        rows = [
            event("a", "external", "2026-10-18T12:00:00+09:00", "explainer_opened"),
            event("a", "external", "2026-10-18T12:01:00+09:00", "source_opened"),
            event("a", "external", "2026-10-25T12:02:00+09:00", "explainer_opened"),
        ]
        result = aggregate_events(
            rows, datetime.fromisoformat("2026-10-26T12:00:00+09:00")
        )
        self.assertEqual(result["all"]["d7_organic_returned"], 0)


class CampaignTest(unittest.TestCase):
    """Check operational data without treating a plan as public readiness."""

    def test_verified_label_without_evidence_does_not_open_launch_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "campaign.json").write_text(
                json.dumps(
                    {
                        "campaign_id": "test",
                        "collector_until": "2026-10-24T00:00:00+09:00",
                    }
                )
            )
            (root / "readiness.json").write_text(
                json.dumps(
                    {
                        "public_base_url": "https://beta.example.org",
                        "checks": [
                            {
                                "label": "human review",
                                "status": "verified",
                                "evidence": None,
                            }
                        ],
                    }
                )
            )
            (root / "budget.csv").write_text("planned_krw,actual_krw\n0,0\n")
            (root / "content-board.csv").write_text(
                "asset_id,format,scheduled_at,status\n"
            )
            result = check(root, datetime.fromisoformat("2026-10-17T20:00:00+09:00"))
            self.assertIn("human review", result["launch_blockers"])

    def test_public_link_rejects_local_private_auth_and_http(self):
        for url in [
            "http://example.com",
            "https://127.0.0.1",
            "https://10.0.1.2",
            "https://localhost",
            "https://user:pass@example.com",
            "https://app.local",
            "https://[::1]",
        ]:
            self.assertFalse(public_https(url), url)
        self.assertTrue(
            public_https("https://beta.example.org/issues/one?utm_source=instagram")
        )

    def test_budget_preserves_missing_actual_spend_and_overrun(self):
        rows = [
            {"planned_krw": "60000", "actual_krw": ""},
            {"planned_krw": "20000", "actual_krw": ""},
            {"planned_krw": "20000", "actual_krw": ""},
        ]
        result = budget_summary(rows)
        self.assertEqual(result["planned_total_krw"], 100000)
        self.assertIsNone(result["actual_total_krw"])
        self.assertTrue(result["within_budget"])
        with self.assertRaises(ValueError):
            budget_summary([{"planned_krw": "100001", "actual_krw": ""}])

    def test_negative_budget_row_cannot_be_hidden_by_other_rows(self):
        with self.assertRaises(ValueError):
            budget_summary(
                [
                    {"planned_krw": "-1000", "actual_krw": ""},
                    {"planned_krw": "2000", "actual_krw": ""},
                ]
            )

    def test_deadline_requires_renewal_without_assuming_monthlong_watch(self):
        self.assertEqual(
            deadline_state(
                "2026-10-24T00:00:00+09:00",
                datetime.fromisoformat("2026-10-24T00:00:00+09:00"),
            ),
            "expired",
        )
        self.assertEqual(
            deadline_state(
                "2026-10-24T00:00:00+09:00",
                datetime.fromisoformat("2026-10-23T00:00:00+09:00"),
            ),
            "renewal_due",
        )

    def test_board_detects_premature_publish_and_wrong_asset_mix(self):
        rows = [
            {
                "asset_id": "B01",
                "format": "carousel",
                "scheduled_at": "2026-10-19T19:30:00+09:00",
                "status": "published",
                "review_status": "pending",
                "app_url": "",
                "published_url": "",
            }
        ]
        errors = validate_board(rows)
        self.assertTrue(any("12" in value for value in errors))
        self.assertTrue(any("B01" in value for value in errors))


class ReportSourceGateTest(unittest.TestCase):
    """Prevent disposable local-QA observations from entering campaign totals."""

    def fixture(self, measurement_source, public_url):
        """Build isolated input files without altering the live readiness gate."""
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        source_root = Path(__file__).resolve().parent / "fixtures/campaign"
        for name in ["campaign.json", "content-board.csv", "budget.csv"]:
            (root / name).write_text(
                (source_root / name).read_text(encoding="utf-8-sig"), encoding="utf-8"
            )
        readiness = {
            "public_base_url": public_url,
            "checks": [
                {"label": "human review", "status": "pending", "evidence": None}
            ],
        }
        if measurement_source is not None:
            readiness["measurement_source"] = measurement_source
        (root / "readiness.json").write_text(json.dumps(readiness))
        backend = {
            "observedAt": "2026-10-26T12:00:00+09:00",
            "calendarZone": "Asia/Seoul",
            "retentionDays": 35,
            "cohorts": [
                {
                    "cohort": "external",
                    "enrolled": 1,
                    "activated": 1,
                    "d7Eligible": 1,
                    "d7Returned": 1,
                    "organicReturned": 0,
                    "researchReturned": 1,
                    "d7Retention": 1.0,
                }
            ],
            "acquisition": {"instagram": 0},
        }
        backend_path = root / "backend.json"
        backend_path.write_text(json.dumps(backend))
        events_path = root / "events.csv"
        rows = [
            event(
                "test-only", "external", "2026-10-18T12:00:00+09:00", "explainer_opened"
            ),
            event(
                "test-only", "external", "2026-10-18T12:01:00+09:00", "source_opened"
            ),
        ]
        with events_path.open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        return root, events_path, backend_path

    def test_local_qa_inputs_are_ignored_instead_of_reported_as_real_people(self):
        root, events, backend = self.fixture(
            {"environment": "local-qa", "includeInCampaignMetrics": False},
            "https://beta.example.org",
        )
        result = report(
            root, datetime.fromisoformat("2026-10-26T12:00:00+09:00"), events, backend
        )
        self.assertFalse(result["measurement_gate"]["allowed"])
        self.assertIsNone(result["research_export"]["all"]["enrolled"])
        self.assertIsNone(result["backend_metrics"]["cohorts"]["external"]["enrolled"])
        self.assertEqual(
            set(result["ignored_measurement_inputs"]), {"events", "backend-report"}
        )
        self.assertTrue(any("QA" in note for note in result["measurement_notes"]))

    def test_explicit_production_can_import_zero_and_rates_before_human_launch_checks(
        self,
    ):
        root, events, backend = self.fixture(
            {"environment": "production-beta", "includeInCampaignMetrics": True},
            "https://beta.example.org",
        )
        result = report(
            root, datetime.fromisoformat("2026-10-26T12:00:00+09:00"), events, backend
        )
        self.assertTrue(result["measurement_gate"]["allowed"])
        self.assertFalse(result["launch_ready"])
        self.assertEqual(
            result["backend_metrics"]["cohorts"]["external"]["d7_organic_rate"], 0.0
        )
        self.assertEqual(
            result["backend_metrics"]["cohorts"]["external"]["d7_total_rate"], 1.0
        )
        self.assertEqual(result["backend_metrics"]["acquisition"], {"instagram": 0})
        self.assertEqual(result["research_export"]["all"]["enrolled"], 1)
        self.assertEqual(result["ignored_measurement_inputs"], [])

    def test_missing_inclusion_flag_fails_closed(self):
        root, events, backend = self.fixture(
            {"environment": "production-beta"}, "https://beta.example.org"
        )
        result = report(
            root, datetime.fromisoformat("2026-10-26T12:00:00+09:00"), events, backend
        )
        self.assertFalse(result["measurement_gate"]["allowed"])
        self.assertIsNone(result["research_export"]["all"]["activated"])

    def test_missing_source_and_loopback_url_fail_closed(self):
        for source, url in [
            (None, "https://beta.example.org"),
            (
                {"environment": "production-beta", "includeInCampaignMetrics": True},
                "https://127.0.0.1",
            ),
        ]:
            with self.subTest(source=source, url=url):
                root, events, backend = self.fixture(source, url)
                result = report(
                    root,
                    datetime.fromisoformat("2026-10-26T12:00:00+09:00"),
                    events,
                    backend,
                )
                self.assertFalse(result["measurement_gate"]["allowed"])
                self.assertIsNone(
                    result["backend_metrics"]["cohorts"]["external"]["activated"]
                )


if __name__ == "__main__":
    unittest.main()
