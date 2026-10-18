"""Tests for pure lifecycle decisions; no network or filesystem writes."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from lifecycle_decisions import decide


class LifecycleDecisionTests(unittest.TestCase):
    def test_missing_signals_never_approve_waiting_move(self):
        self.assertEqual(decide("Waiting", 100, 30)[0], "unknown")

    def test_missing_signals_never_approve_holding_move(self):
        self.assertEqual(decide("Holding", 100, 7)[0], "unknown")

    def test_favorite_overrides_expired_waiting(self):
        self.assertEqual(decide("Waiting", 100, 30, {"favorite": True})[0], "keep")

    def test_protection_overrides_disliked(self):
        self.assertEqual(decide("Waiting", 100, 30, {"protected": True, "disliked": True})[0], "keep")

    def test_disliked_moves_early(self):
        self.assertEqual(decide("Waiting", 0, 30, {"disliked": True})[0], "hold")

    def test_waiting_deadline(self):
        self.assertEqual(decide("Waiting", 30, 30, {})[0], "hold")

    def test_holding_favorite_rescues(self):
        self.assertEqual(decide("Holding", 20, 7, {"favorite": True})[0], "rescue")

    def test_holding_deadline(self):
        self.assertEqual(decide("Holding", 7, 7, {})[0], "to_removal")

    def test_keep_tag_moves_waiting_to_keep(self):
        self.assertEqual(decide("Waiting", 0, 30, {"keep": True})[0], "keep")

    def test_keep_tag_rescues_holding(self):
        self.assertEqual(decide("Holding", 0, 7, {"keep": True})[0], "rescue")

    def test_legacy_favorite_can_be_disabled(self):
        self.assertEqual(decide("Waiting", 0, 30, {"favorite": True}, False)[0], "wait")

    def test_protected_wins_when_legacy_favorites_disabled(self):
        self.assertEqual(decide("Waiting", 100, 30, {"protected": True, "disliked": True}, False)[0], "keep")

    def test_keep_wins_over_dislike(self):
        self.assertEqual(decide("Waiting", 0, 30, {"keep": True, "disliked": True}, False)[0], "keep")

    def test_removal_deadline_is_only_candidate(self):
        self.assertEqual(decide("Removal", 7, 7)[0], "delete_candidate")


if __name__ == "__main__":
    unittest.main()
