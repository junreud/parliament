"""Daily editorial gates must preserve evidence and real publication timing."""

import copy
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from marketing.campaign import validate_board
from marketing.growth import observation, publication_preflight, save_observation

CONFIG = {
    "timezone": "Asia/Seoul",
    "assets": {"carousel": 1, "reel": 1},
    "publication": {
        "start_date": "2026-10-21",
        "end_date": "2026-10-22",
        "weekdays": list(range(7)),
        "time": "19:30",
        "daily_limit": 1,
    },
}


def rows():
    """Return two planned days with no fictional reservations or metrics."""
    return [
        {
            "asset_id": f"B{index:02}",
            "scheduled_at": f"2026-10-{20 + index}T19:30:00+09:00",
            "format": kind,
            "status": "ready",
            "review_status": "approved",
            "approval_evidence": "approvals/owner.json",
            "primary_source_urls": "https://www.law.go.kr/example",
            "source_evidence": "evidence/immutable.json",
            "source_checked_at": "2026-10-20T21:00:00+09:00",
            "cta_type": "account_followup",
        }
        for index, kind in enumerate(["carousel", "reel"], 1)
    ]


class DailyBoardTest(unittest.TestCase):
    def test_source_only_posts_do_not_require_unreleased_app(self):
        self.assertEqual(validate_board(rows(), CONFIG), [])

    def test_utc_slots_are_compared_in_seoul_and_one_per_day(self):
        board = rows()
        board[0]["scheduled_at"] = "2026-10-21T10:30:00+00:00"
        self.assertEqual(validate_board(board, CONFIG), [])
        board[1]["scheduled_at"] = "2026-10-21T19:30:00+09:00"
        self.assertTrue(any("duplicate" in e for e in validate_board(board, CONFIG)))

    def test_app_cta_needs_verified_exact_public_link(self):
        board = rows()
        board[0]["cta_type"] = "app_issue"
        board[0]["app_url"] = "https://app.example.org/issues/one"
        errors = validate_board(board, CONFIG)
        self.assertTrue(any("app" in e for e in errors))
        board[0].update(
            app_link_verified_at="2026-10-20T20:00:00+09:00",
            app_link_evidence="evidence/public-link.json",
            app_issue_id="one",
        )
        self.assertEqual(validate_board(board, CONFIG), [])

    def test_schedule_receipt_cannot_replace_published_url_and_time(self):
        board = rows()
        board[0].update(
            status="scheduled",
            scheduler_id="123",
            scheduler_receipt="evidence/receipt.json",
        )
        self.assertEqual(validate_board(board, CONFIG), [])
        board[0]["status"] = "published"
        self.assertTrue(any("published" in e for e in validate_board(board, CONFIG)))

    def test_missing_source_or_approval_is_held(self):
        for key in [
            "review_status",
            "approval_evidence",
            "source_evidence",
            "primary_source_urls",
        ]:
            board = rows()
            board[0][key] = ""
            self.assertTrue(validate_board(board, CONFIG), key)

    def test_bad_date_returns_validation_error(self):
        board = rows()
        board[0]["scheduled_at"] = "not-a-date"
        self.assertTrue(validate_board(board, CONFIG))


class PublicationTest(unittest.TestCase):
    def test_observation_is_persisted_once_per_asset_and_window(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            value = {"asset_id": "B01", "window_hours": 24, "reach": 3}
            saved = save_observation(value, state)
            self.assertTrue(saved.is_file())
            with self.assertRaises(FileExistsError):
                save_observation(value, state)

    def test_preflight_holds_unverified_app_cta(self):
        row = rows()[0]
        row["cta_type"] = "app_issue"
        row["app_url"] = "https://app.example.org/issues/one"
        now = datetime.fromisoformat("2026-10-21T18:00:00+09:00")
        self.assertTrue(any("app" in e for e in publication_preflight(row, now)))

    def test_preflight_never_backdates_and_rechecks_source(self):
        row = rows()[0]
        now = datetime.fromisoformat("2026-10-21T18:00:00+09:00")
        self.assertEqual(publication_preflight(row, now), [])
        past = datetime.fromisoformat("2026-10-21T20:00:00+09:00")
        self.assertTrue(any("elapsed" in e for e in publication_preflight(row, past)))
        stale = copy.deepcopy(row)
        stale["source_checked_at"] = "2026-10-19T18:00:00+09:00"
        self.assertTrue(
            any("freshness" in e for e in publication_preflight(stale, now))
        )

    def test_24_72_observations_require_actual_post_and_matching_url(self):
        row = rows()[0]
        now = datetime.fromisoformat("2026-10-22T20:00:00+09:00")
        self.assertIsNone(observation(row, {}, now, 24))
        row.update(
            published_url="https://www.instagram.com/p/one/",
            published_at="2026-10-21T19:30:00+09:00",
        )
        raw = {"url": row["published_url"], "reach": 100, "saves": 4, "shares": 2}
        result = observation(row, raw, now, 24)
        self.assertEqual(result["elapsed_hours"], 24.5)
        self.assertEqual(result["saves_per_100_reached"], 4)
        self.assertIsNone(result["profile_visits"])
        self.assertIsNone(observation(row, raw, now, 72))
        self.assertIsNone(observation(row, dict(raw, url="other"), now, 24))
        row["observation_24h_evidence"] = "evidence/already.json"
        self.assertIsNone(observation(row, raw, now, 24))


if __name__ == "__main__":
    unittest.main()
