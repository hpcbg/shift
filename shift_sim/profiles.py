"""
Synthetic environment profiles: outdoor temperature, renewable share and the
time-of-use heat tariff.

All profiles are deterministic functions of hour-of-day (0..24). They are
SYNTHETIC ASSUMPTIONS, not measured data. Prices are EUR/MWh (thermal).

Event-driven overrides (e.g. a PRICE_OFFER lowering the price and raising the
renewable share for a window) are applied by the simulator, not here — these are
the undisturbed base profiles.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Tuple

from .config import parse_clock


class Profiles:
    def __init__(self, config: Dict[str, Any]) -> None:
        w = config["weather"]
        self.coldest_c = float(w["coldest_c"])
        self.coldest_hour = float(w["coldest_hour"])
        self.swing_c = float(w["daily_swing_c"])

        r = config["renewable"]
        self.base_share = float(r["base_share"])
        self.peak_share = float(r["midday_peak_share"])
        self.peak_hour = float(r["peak_hour"])
        self.spread = float(r["spread_hours"])

        t = config["tariff"]
        self.default_price = float(t["default_price_eur_per_mwh"])
        self._periods: List[Tuple[float, float, float]] = []
        for p in t.get("periods", []):
            self._periods.append(
                (parse_clock(p["start"]), parse_clock(p["end"]),
                 float(p["price_eur_per_mwh"]))
            )

    def outdoor_temp_c(self, hour: float) -> float:
        """Sinusoidal daily outdoor temperature; minimum at ``coldest_hour``."""
        mean = self.coldest_c + self.swing_c / 2.0
        amp = self.swing_c / 2.0
        # cos == 1 at coldest_hour -> value == coldest_c
        return mean - amp * math.cos(2.0 * math.pi * (hour - self.coldest_hour) / 24.0)

    def renewable_share(self, hour: float) -> float:
        """Gaussian bump peaking at midday; clamped to [0, 1]."""
        val = self.base_share + (self.peak_share - self.base_share) * math.exp(
            -((hour - self.peak_hour) ** 2) / (2.0 * self.spread ** 2)
        )
        return max(0.0, min(1.0, val))

    def price_eur_per_mwh(self, hour: float) -> float:
        """Time-of-use tariff lookup; falls back to the default price."""
        h = hour % 24.0
        for start, end, price in self._periods:
            if start <= end:
                if start <= h < end:
                    return price
            else:  # wraps past midnight
                if h >= start or h < end:
                    return price
        return self.default_price
