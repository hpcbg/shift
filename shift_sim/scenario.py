"""
Scenario definitions.

Baseline and SHIFT are the *same engine, same config, different ScenarioDef*.
Physical events (window/door/fault, cold snap) apply to both scenarios; only the
control response (preheat / reduce / stagger) differs.
"""

from __future__ import annotations

from dataclasses import dataclass

BASELINE = "baseline"
SHIFT = "shift"


@dataclass(frozen=True)
class ScenarioDef:
    name: str            # "baseline" | "shift"
    apply_control: bool  # baseline=False (schedule only), shift=True

    @staticmethod
    def baseline() -> "ScenarioDef":
        return ScenarioDef(name=BASELINE, apply_control=False)

    @staticmethod
    def shift() -> "ScenarioDef":
        return ScenarioDef(name=SHIFT, apply_control=True)
