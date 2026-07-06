"""
Configuration loading for SHIFT.

Loads ``config.yaml`` and deep-merges an optional machine-local
``config.local.yaml`` on top of it (pattern adapted from HARVEST, re-implemented
here — no HARVEST code is imported).

All configuration values are SYNTHETIC ASSUMPTIONS. Prices are in EUR/MWh.
"""

from __future__ import annotations

import copy
from datetime import datetime, time
from pathlib import Path
from typing import Any, Dict

import yaml

# Repository root = parent of the shift_sim package directory.
ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = ROOT / "config.yaml"
LOCAL_CONFIG = ROOT / "config.local.yaml"


def load_yaml(path: str | Path) -> Dict[str, Any]:
    """Load a single YAML file into a dict."""
    with open(path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return data or {}


def deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively merge ``override`` onto a deep copy of ``base``.

    Dicts merge key-by-key; every other type (including lists) is replaced
    wholesale by the override value.
    """
    result = copy.deepcopy(base)
    for key, val in (override or {}).items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = deep_merge(result[key], val)
        else:
            result[key] = copy.deepcopy(val)
    return result


def load_config(path: str | Path | None = None,
                local_path: str | Path | None = None) -> Dict[str, Any]:
    """Load the base config and deep-merge the local override if present.

    A missing local override file is tolerated (returns the base config).
    """
    base_path = Path(path) if path else DEFAULT_CONFIG
    cfg = load_yaml(base_path)

    local = Path(local_path) if local_path else LOCAL_CONFIG
    if local.exists():
        cfg = deep_merge(cfg, load_yaml(local))
    return cfg


# ── small parsing helpers shared across the engine ────────────────────────────

def parse_clock(value: str | float | int) -> float:
    """Parse an "HH:MM" string (or a numeric hour) into an hour-of-day float.

    "18:30" -> 18.5 ;  6 -> 6.0 ;  "24:00" -> 24.0
    """
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    hh, _, mm = text.partition(":")
    return int(hh) + (int(mm) / 60.0 if mm else 0.0)


def parse_datetime(value: str) -> datetime:
    """Parse "YYYY-MM-DD HH:MM" (or with seconds) into a datetime."""
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    raise ValueError(f"Unrecognised datetime: {value!r}")
