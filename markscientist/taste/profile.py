"""Taste profile data structures for user preference calibration."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple


@dataclass
class BuddyCalibration:
    """Per-buddy calibration stats derived from user feedback."""

    buddy_name: str
    score_offset: float = 0.0
    agreement_count: int = 0
    disagree_count: int = 0
    too_high_count: int = 0
    too_low_count: int = 0

    @property
    def total_feedback(self) -> int:
        return (
            self.agreement_count
            + self.disagree_count
            + self.too_high_count
            + self.too_low_count
        )

    @property
    def agreement_rate(self) -> float:
        if self.total_feedback == 0:
            return 0.0
        return self.agreement_count / self.total_feedback

    def to_dict(self) -> Dict[str, Any]:
        return {
            "buddy_name": self.buddy_name,
            "score_offset": self.score_offset,
            "agreement_count": self.agreement_count,
            "disagree_count": self.disagree_count,
            "too_high_count": self.too_high_count,
            "too_low_count": self.too_low_count,
            "total_feedback": self.total_feedback,
            "agreement_rate": self.agreement_rate,
        }


@dataclass
class TasteProfile:
    """User's taste profile with per-buddy calibrations."""

    buddy_calibrations: Dict[str, BuddyCalibration] = field(default_factory=dict)
    min_feedback_threshold: int = 3

    def has_calibration(self, buddy_name: Optional[str] = None) -> bool:
        """Check if profile has enough data for calibration.

        Args:
            buddy_name: Check specific buddy. If None, checks any calibration.
        """
        if buddy_name:
            cal = self.buddy_calibrations.get(buddy_name)
            return cal is not None and cal.total_feedback >= self.min_feedback_threshold
        return any(
            cal.total_feedback >= self.min_feedback_threshold
            for cal in self.buddy_calibrations.values()
        )

    def apply_to_score(
        self, score: float, buddy_name: str
    ) -> Tuple[float, Dict[str, Any]]:
        """Apply taste calibration to a score.

        Args:
            score: Original score (0-10)
            buddy_name: Name of the buddy that produced the score

        Returns:
            Tuple of (adjusted_score, calibration_metadata)
        """
        metadata = {
            "original_score": score,
            "buddy_name": buddy_name,
            "calibration_applied": False,
            "offset": 0.0,
        }

        cal = self.buddy_calibrations.get(buddy_name)
        if cal is None or cal.total_feedback < self.min_feedback_threshold:
            return score, metadata

        # Apply offset
        adjusted = score + cal.score_offset

        # Clamp to 0-10 range
        adjusted = max(0.0, min(10.0, adjusted))

        metadata["calibration_applied"] = True
        metadata["offset"] = cal.score_offset
        metadata["adjusted_score"] = adjusted
        metadata["feedback_count"] = cal.total_feedback

        return adjusted, metadata

    def get_calibration(self, buddy_name: str) -> Optional[BuddyCalibration]:
        """Get calibration for a specific buddy."""
        return self.buddy_calibrations.get(buddy_name)

    def get_total_feedback_count(self) -> int:
        """Get total feedback count across all buddies."""
        return sum(cal.total_feedback for cal in self.buddy_calibrations.values())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "buddy_calibrations": {
                name: cal.to_dict() for name, cal in self.buddy_calibrations.items()
            },
            "min_feedback_threshold": self.min_feedback_threshold,
            "total_feedback": self.get_total_feedback_count(),
        }
