"""Tests for the taste learning module."""

import json
import tempfile
from pathlib import Path

import pytest

from markscientist.taste import (
    BuddyCalibration,
    TasteProfile,
    TasteProfileLoader,
    get_taste_profile,
    set_taste_profile,
)


class TestBuddyCalibration:
    """Tests for BuddyCalibration dataclass."""

    def test_total_feedback(self):
        cal = BuddyCalibration(
            buddy_name="Professor Owl",
            agreement_count=5,
            disagree_count=2,
            too_high_count=3,
            too_low_count=1,
        )
        assert cal.total_feedback == 11

    def test_agreement_rate(self):
        cal = BuddyCalibration(
            buddy_name="Professor Owl",
            agreement_count=5,
            disagree_count=2,
            too_high_count=2,
            too_low_count=1,
        )
        assert cal.agreement_rate == pytest.approx(0.5)

    def test_agreement_rate_zero_feedback(self):
        cal = BuddyCalibration(buddy_name="Professor Owl")
        assert cal.agreement_rate == 0.0

    def test_to_dict(self):
        cal = BuddyCalibration(
            buddy_name="Professor Owl",
            score_offset=-0.5,
            agreement_count=3,
            too_high_count=2,
        )
        result = cal.to_dict()
        assert result["buddy_name"] == "Professor Owl"
        assert result["score_offset"] == -0.5
        assert result["agreement_count"] == 3
        assert result["too_high_count"] == 2
        assert result["total_feedback"] == 5


class TestTasteProfile:
    """Tests for TasteProfile."""

    def test_empty_profile_no_calibration(self):
        profile = TasteProfile()
        assert not profile.has_calibration()
        assert not profile.has_calibration("Professor Owl")

    def test_has_calibration_below_threshold(self):
        profile = TasteProfile(
            buddy_calibrations={
                "Professor Owl": BuddyCalibration(
                    buddy_name="Professor Owl",
                    too_high_count=2,
                )
            },
            min_feedback_threshold=3,
        )
        assert not profile.has_calibration("Professor Owl")

    def test_has_calibration_meets_threshold(self):
        profile = TasteProfile(
            buddy_calibrations={
                "Professor Owl": BuddyCalibration(
                    buddy_name="Professor Owl",
                    too_high_count=3,
                )
            },
            min_feedback_threshold=3,
        )
        assert profile.has_calibration("Professor Owl")
        assert profile.has_calibration()

    def test_apply_to_score_no_calibration(self):
        profile = TasteProfile()
        adjusted, meta = profile.apply_to_score(7.5, "Professor Owl")
        assert adjusted == 7.5
        assert meta["calibration_applied"] is False
        assert meta["original_score"] == 7.5

    def test_apply_to_score_with_offset(self):
        profile = TasteProfile(
            buddy_calibrations={
                "Professor Owl": BuddyCalibration(
                    buddy_name="Professor Owl",
                    score_offset=-1.0,
                    too_high_count=5,
                )
            },
            min_feedback_threshold=3,
        )
        adjusted, meta = profile.apply_to_score(8.0, "Professor Owl")
        assert adjusted == 7.0
        assert meta["calibration_applied"] is True
        assert meta["offset"] == -1.0
        assert meta["adjusted_score"] == 7.0

    def test_apply_to_score_clamp_low(self):
        profile = TasteProfile(
            buddy_calibrations={
                "Professor Owl": BuddyCalibration(
                    buddy_name="Professor Owl",
                    score_offset=-2.0,
                    too_high_count=5,
                )
            },
            min_feedback_threshold=3,
        )
        adjusted, meta = profile.apply_to_score(1.0, "Professor Owl")
        assert adjusted == 0.0  # Clamped to minimum

    def test_apply_to_score_clamp_high(self):
        profile = TasteProfile(
            buddy_calibrations={
                "Professor Owl": BuddyCalibration(
                    buddy_name="Professor Owl",
                    score_offset=2.0,
                    too_low_count=5,
                )
            },
            min_feedback_threshold=3,
        )
        adjusted, meta = profile.apply_to_score(9.5, "Professor Owl")
        assert adjusted == 10.0  # Clamped to maximum

    def test_get_total_feedback_count(self):
        profile = TasteProfile(
            buddy_calibrations={
                "Professor Owl": BuddyCalibration(
                    buddy_name="Professor Owl",
                    agreement_count=3,
                    too_high_count=2,
                ),
                "Captain Crit": BuddyCalibration(
                    buddy_name="Captain Crit",
                    too_low_count=4,
                ),
            }
        )
        assert profile.get_total_feedback_count() == 9


class TestTasteProfileLoader:
    """Tests for TasteProfileLoader."""

    def test_load_empty_file(self, tmp_path: Path):
        feedback_file = tmp_path / "feedback_history.jsonl"
        feedback_file.touch()

        loader = TasteProfileLoader(feedback_path=feedback_file)
        records = loader.load_feedback_records()
        assert records == []

    def test_load_missing_file(self, tmp_path: Path):
        feedback_file = tmp_path / "nonexistent.jsonl"

        loader = TasteProfileLoader(feedback_path=feedback_file)
        records = loader.load_feedback_records()
        assert records == []

    def test_load_valid_records(self, tmp_path: Path):
        feedback_file = tmp_path / "feedback_history.jsonl"
        records = [
            {"buddy_name": "Professor Owl", "user_reaction": "too_high", "score": 8.5},
            {"buddy_name": "Professor Owl", "user_reaction": "too_high", "score": 9.0},
            {"buddy_name": "Professor Owl", "user_reaction": "agree", "score": 7.0},
        ]
        with open(feedback_file, "w") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")

        loader = TasteProfileLoader(feedback_path=feedback_file)
        loaded = loader.load_feedback_records()
        assert len(loaded) == 3

    def test_aggregate_to_profile(self, tmp_path: Path):
        records = [
            {"buddy_name": "Professor Owl", "user_reaction": "too_high"},
            {"buddy_name": "Professor Owl", "user_reaction": "too_high"},
            {"buddy_name": "Professor Owl", "user_reaction": "too_high"},
            {"buddy_name": "Professor Owl", "user_reaction": "agree"},
        ]

        loader = TasteProfileLoader(min_feedback_threshold=3)
        profile = loader.aggregate_to_profile(records)

        assert profile.has_calibration("Professor Owl")
        cal = profile.get_calibration("Professor Owl")
        assert cal.too_high_count == 3
        assert cal.agreement_count == 1
        assert cal.score_offset < 0  # Should be negative (need to lower scores)

    def test_aggregate_multiple_buddies(self, tmp_path: Path):
        records = [
            {"buddy_name": "Professor Owl", "user_reaction": "too_high"},
            {"buddy_name": "Professor Owl", "user_reaction": "too_high"},
            {"buddy_name": "Professor Owl", "user_reaction": "too_high"},
            {"buddy_name": "Captain Crit", "user_reaction": "too_low"},
            {"buddy_name": "Captain Crit", "user_reaction": "too_low"},
            {"buddy_name": "Captain Crit", "user_reaction": "too_low"},
            {"buddy_name": "Captain Crit", "user_reaction": "too_low"},
        ]

        loader = TasteProfileLoader(min_feedback_threshold=3)
        profile = loader.aggregate_to_profile(records)

        owl_cal = profile.get_calibration("Professor Owl")
        crit_cal = profile.get_calibration("Captain Crit")

        assert owl_cal.score_offset < 0  # Should lower scores
        assert crit_cal.score_offset > 0  # Should raise scores

    def test_calculate_offset_balanced(self):
        loader = TasteProfileLoader()
        offset = loader._calculate_offset(too_high=3, too_low=3)
        assert offset == 0.0

    def test_calculate_offset_too_high(self):
        loader = TasteProfileLoader()
        offset = loader._calculate_offset(too_high=5, too_low=0)
        assert offset < 0  # Should be negative

    def test_calculate_offset_too_low(self):
        loader = TasteProfileLoader()
        offset = loader._calculate_offset(too_high=0, too_low=5)
        assert offset > 0  # Should be positive

    def test_calculate_offset_capped(self):
        loader = TasteProfileLoader()
        # Very strong feedback should still be capped
        offset = loader._calculate_offset(too_high=100, too_low=0)
        assert offset >= -2.0

        offset = loader._calculate_offset(too_high=0, too_low=100)
        assert offset <= 2.0

    def test_full_load(self, tmp_path: Path):
        feedback_file = tmp_path / "feedback_history.jsonl"
        records = [
            {"buddy_name": "Professor Owl", "user_reaction": "too_high"},
            {"buddy_name": "Professor Owl", "user_reaction": "too_high"},
            {"buddy_name": "Professor Owl", "user_reaction": "too_high"},
        ]
        with open(feedback_file, "w") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")

        loader = TasteProfileLoader(feedback_path=feedback_file)
        profile = loader.load()

        assert profile.has_calibration("Professor Owl")


class TestGlobalProfile:
    """Tests for global profile singleton."""

    def test_set_and_get_profile(self):
        test_profile = TasteProfile(
            buddy_calibrations={
                "Test Buddy": BuddyCalibration(
                    buddy_name="Test Buddy",
                    too_high_count=5,
                )
            }
        )
        set_taste_profile(test_profile)
        retrieved = get_taste_profile()
        assert retrieved is test_profile


class TestBackwardCompatibility:
    """Tests for backward compatibility."""

    def test_no_feedback_file_works(self, tmp_path: Path):
        # Simulate missing file scenario
        nonexistent_path = tmp_path / "does_not_exist" / "feedback_history.jsonl"
        loader = TasteProfileLoader(feedback_path=nonexistent_path)
        profile = loader.load()

        # Should return empty profile, not error
        assert not profile.has_calibration()
        assert profile.get_total_feedback_count() == 0

    def test_empty_profile_passthrough(self):
        profile = TasteProfile()

        # All scores should pass through unchanged
        for score in [0.0, 5.0, 7.5, 10.0]:
            adjusted, meta = profile.apply_to_score(score, "Any Buddy")
            assert adjusted == score
            assert meta["calibration_applied"] is False
