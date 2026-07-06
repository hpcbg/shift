"""
Synthetic environment profiles: outdoor temperature, renewable share and the
time-of-use heat tariff.

All profiles are deterministic functions of hour-of-day (0..24). They are
SYNTHETIC ASSUMPTIONS, not measured data. Prices are EUR/MWh (thermal).

Outdoor temperature is, by default, a config-driven hourly profile
(``weather.hourly_temperature_c``) linearly interpolated between the configured
points. The same interface accepts measured or forecast hourly data. If the
hourly profile is absent, the engine falls back to the legacy sinusoidal profile
(``coldest_c`` / ``coldest_hour`` / ``daily_swing_c``).

Event-driven overrides (e.g. a PRICE_OFFER lowering the price and raising the
renewable share for a window) are applied by the simulator, not here — these are
the undisturbed base profiles.
"""

from __future__ import annotations

import bisect
import math
from typing import Any, Dict, List, Tuple

from .config import parse_clock


class Profiles:
    def __init__(self, config: Dict[str, Any]) -> None:
        w = config["weather"]
        self.profile_name = str(w.get("profile_name", ""))

        pts = w.get("hourly_temperature_c")
        if pts:
            self._use_hourly = True
            self._temp_hours, self._temp_values = self._build_hourly_profile(pts)
        else:
            # Legacy sinusoidal fallback — requires the coldest_* / swing keys.
            self._use_hourly = False
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

    # ── hourly temperature profile ────────────────────────────────────────────
    @staticmethod
    def _build_hourly_profile(pts: List[Dict[str, Any]]) -> Tuple[List[float], List[float]]:
        """Validate and unpack the ordered {hour, value} points.

        Rules: strictly increasing hours; finite values; coverage from hour 0
        through hour 24.
        """
        hours: List[float] = []
        values: List[float] = []
        prev_h = None
        for p in pts:
            h = float(p["hour"])
            v = float(p["value"])
            if not math.isfinite(h) or not math.isfinite(v):
                raise ValueError(f"weather.hourly_temperature_c: non-finite point {p!r}")
            if prev_h is not None and h <= prev_h:
                raise ValueError(
                    "weather.hourly_temperature_c: hours must be strictly increasing "
                    f"(got {h} after {prev_h})")
            prev_h = h
            hours.append(h)
            values.append(v)

        if len(hours) < 2:
            raise ValueError("weather.hourly_temperature_c: need at least two points")
        if hours[0] > 1e-9:
            raise ValueError(
                f"weather.hourly_temperature_c: must cover hour 0 (first hour = {hours[0]})")
        if hours[-1] < 24.0 - 1e-9:
            raise ValueError(
                f"weather.hourly_temperature_c: must cover hour 24 (last hour = {hours[-1]})")
        return hours, values

    def outdoor_temp_c(self, hour: float) -> float:
        """Outdoor temperature at ``hour`` [deg C].

        Hourly profile: exact configured value at each defined hour, deterministic
        linear interpolation between them. Sinusoidal fallback otherwise.
        """
        if self._use_hourly:
            H, V = self._temp_hours, self._temp_values
            if hour <= H[0]:
                return V[0]
            if hour >= H[-1]:
                return V[-1]
            i = bisect.bisect_right(H, hour)   # first index with H[i] > hour
            h0, h1 = H[i - 1], H[i]
            v0, v1 = V[i - 1], V[i]
            fraction = (hour - h0) / (h1 - h0)
            return v0 + fraction * (v1 - v0)

        # legacy sinusoidal: minimum at coldest_hour
        mean = self.coldest_c + self.swing_c / 2.0
        amp = self.swing_c / 2.0
        return mean - amp * math.cos(2.0 * math.pi * (hour - self.coldest_hour) / 24.0)

    def outdoor_temp_bounds(self) -> Tuple[float, float]:
        """(minimum, maximum) outdoor temperature of the active profile [deg C]."""
        if self._use_hourly:
            return (min(self._temp_values), max(self._temp_values))
        return (self.coldest_c, self.coldest_c + self.swing_c)

    # ── renewable share & tariff (unchanged) ──────────────────────────────────
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
