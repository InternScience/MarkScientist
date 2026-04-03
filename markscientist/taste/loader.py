"""Taste profile loader from feedback history."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from .profile import BuddyCalibration, TasteProfile


class TasteProfileLoader:
    """Loads and aggregates user feedback into a TasteProfile."""

    def __init__(
        self,
        feedback_path: Optional[Path] = None,
        min_feedback_threshold: int = 3,
    ):
        """Initialize loader.

        Args:
            feedback_path: Path to feedback_history.jsonl.
                          Defaults to ~/.markscientist/taste/feedback_history.jsonl
            min_feedback_threshold: Minimum feedback points before applying calibration.
        """
        if feedback_path is None:
            feedback_path = (
                Path.home() / ".markscientist" / "taste" / "feedback_history.jsonl"
            )
        self.feedback_path = feedback_path
        self.min_feedback_threshold = min_feedback_threshold

    def load_feedback_records(self) -> List[Dict[str, Any]]:
        """Load all feedback records from the history file."""
        if not self.feedback_path.exists():
            return []

        records = []
        try:
            with open(self.feedback_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            records.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue
        except (OSError, IOError):
            return []

        return records

    def aggregate_to_profile(self, records: List[Dict[str, Any]]) -> TasteProfile:
        """Aggregate feedback records into a TasteProfile.

        Args:
            records: List of feedback records from JSONL

        Returns:
            TasteProfile with computed calibrations
        """
        buddy_stats: Dict[str, Dict[str, int]] = {}

        for record in records:
            buddy_name = record.get("buddy_name")
            reaction = record.get("user_reaction")

            if not buddy_name or not reaction:
                continue

            if buddy_name not in buddy_stats:
                buddy_stats[buddy_name] = {
                    "agree": 0,
                    "disagree": 0,
                    "too_high": 0,
                    "too_low": 0,
                }

            if reaction == "agree":
                buddy_stats[buddy_name]["agree"] += 1
            elif reaction == "disagree":
                buddy_stats[buddy_name]["disagree"] += 1
            elif reaction == "too_high":
                buddy_stats[buddy_name]["too_high"] += 1
            elif reaction == "too_low":
                buddy_stats[buddy_name]["too_low"] += 1

        # Build calibrations
        calibrations: Dict[str, BuddyCalibration] = {}

        for buddy_name, stats in buddy_stats.items():
            # Calculate score offset from too_high/too_low feedback
            # Each too_high suggests we should lower scores, each too_low suggests raise
            offset = self._calculate_offset(
                stats["too_high"],
                stats["too_low"],
            )

            calibrations[buddy_name] = BuddyCalibration(
                buddy_name=buddy_name,
                score_offset=offset,
                agreement_count=stats["agree"],
                disagree_count=stats["disagree"],
                too_high_count=stats["too_high"],
                too_low_count=stats["too_low"],
            )

        return TasteProfile(
            buddy_calibrations=calibrations,
            min_feedback_threshold=self.min_feedback_threshold,
        )

    def _calculate_offset(self, too_high: int, too_low: int) -> float:
        """Calculate score offset from directional feedback.

        Args:
            too_high: Count of "too high" feedback
            too_low: Count of "too low" feedback

        Returns:
            Score offset (negative = lower scores, positive = raise scores)
        """
        total_directional = too_high + too_low
        if total_directional == 0:
            return 0.0

        # Net direction: positive = need to raise scores, negative = need to lower
        net_direction = too_low - too_high

        # Scale the offset based on feedback strength
        # More feedback = stronger adjustment, capped at ±2.0
        # Each directional feedback contributes ~0.3 points
        offset = net_direction * 0.3
        return max(-2.0, min(2.0, offset))

    def load(self) -> TasteProfile:
        """Load feedback and return aggregated TasteProfile."""
        records = self.load_feedback_records()
        return self.aggregate_to_profile(records)


# Global singleton pattern (matches get_config())
_global_taste_profile: Optional[TasteProfile] = None


def get_taste_profile() -> TasteProfile:
    """Get the global taste profile, loading from disk if needed."""
    global _global_taste_profile
    if _global_taste_profile is None:
        loader = TasteProfileLoader()
        _global_taste_profile = loader.load()
    return _global_taste_profile


def reload_taste_profile() -> TasteProfile:
    """Force reload the taste profile from disk."""
    global _global_taste_profile
    loader = TasteProfileLoader()
    _global_taste_profile = loader.load()
    return _global_taste_profile


def set_taste_profile(profile: TasteProfile) -> None:
    """Set the global taste profile (mainly for testing)."""
    global _global_taste_profile
    _global_taste_profile = profile
