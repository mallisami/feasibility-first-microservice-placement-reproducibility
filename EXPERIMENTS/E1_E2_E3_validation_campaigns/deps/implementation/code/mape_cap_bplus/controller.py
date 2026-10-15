"""Slow-timescale change detection and relocation acceptance logic."""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Sequence


@dataclass(frozen=True)
class ReplanDecision:
    should_replan: bool
    reason: str
    candidate_regime: str | None


@dataclass(frozen=True)
class PersistentRegimeDetector:
    minimum_persistent_windows: int = 3
    horizon_safety_factor: float = 1.25

    def evaluate(
        self,
        observed_regimes: Sequence[str],
        current_regime: str,
        forecast_horizon_seconds: float,
        expected_relocation_seconds: float,
    ) -> ReplanDecision:
        if self.minimum_persistent_windows <= 0:
            raise ValueError("minimum_persistent_windows must be positive")
        if self.horizon_safety_factor <= 0:
            raise ValueError("horizon_safety_factor must be positive")
        if not math.isfinite(forecast_horizon_seconds) or not math.isfinite(expected_relocation_seconds):
            raise ValueError("forecast and relocation durations must be finite")
        if forecast_horizon_seconds < 0 or expected_relocation_seconds < 0:
            raise ValueError("forecast and relocation durations must be non-negative")
        if len(observed_regimes) < self.minimum_persistent_windows:
            return ReplanDecision(False, "insufficient persistence history", None)
        tail = tuple(observed_regimes[-self.minimum_persistent_windows :])
        if len(set(tail)) != 1:
            return ReplanDecision(False, "candidate regime is not persistent", None)
        candidate = tail[0]
        if candidate == current_regime:
            return ReplanDecision(False, "persistent regime matches current regime", candidate)
        required_horizon = self.horizon_safety_factor * expected_relocation_seconds
        if forecast_horizon_seconds <= required_horizon:
            return ReplanDecision(
                False,
                f"forecast horizon {forecast_horizon_seconds:.1f}s does not exceed "
                f"relocation threshold {required_horizon:.1f}s",
                candidate,
            )
        return ReplanDecision(True, "persistent regime and economic horizon justify replanning", candidate)


def accept_relocation(
    current_operating_cost: float,
    candidate_operating_cost: float,
    relocation_cost: float,
    uncertainty_margin: float,
    minimum_net_benefit: float = 0.0,
) -> tuple[bool, float, str]:
    values = (current_operating_cost, candidate_operating_cost, relocation_cost, uncertainty_margin, minimum_net_benefit)
    if any(not math.isfinite(value) for value in values):
        raise ValueError("costs, margins, and minimum benefit must be finite")
    if any(value < 0 for value in values):
        raise ValueError("costs, margins, and minimum benefit must be non-negative")
    net_benefit = (
        current_operating_cost
        - candidate_operating_cost
        - relocation_cost
        - uncertainty_margin
    )
    accepted = net_benefit > minimum_net_benefit
    reason = "positive conservative net benefit" if accepted else "insufficient conservative net benefit"
    return accepted, net_benefit, reason
