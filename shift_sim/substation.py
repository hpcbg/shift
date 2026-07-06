"""
Substation technical limits.

In the MVP the substation is represented by its heat-power cap (``Pmax``, held on
the Building) and a fault state (driven by SUBSTATION_FAULT events). This thin
module centralises the substation-limit semantics and is the seam where, in the
pilot, a real FIWARE/SAREF substation adapter would live.

Space heating only: there is no domestic-hot-water tank or hygiene temperature
here (documented future extension).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SubstationLimits:
    """Technical envelope of a building's heat substation."""
    max_heat_power_kw: float          # Pmax
    min_heat_power_kw: float = 0.0     # uncurtailable base heat (non_controllable_heat_kw)

    def clamp(self, q_kw: float, in_fault: bool) -> float:
        if in_fault:
            return 0.0
        return max(self.min_heat_power_kw, min(q_kw, self.max_heat_power_kw))
