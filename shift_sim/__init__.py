"""
SHIFT — Smart Heat Interoperability and Flexibility Technology.

Synthetic pre-pilot district-heating demand-response simulation engine.
Pure Python, standard library only. No real Miesto Gijos data are used; all
buildings, prices and renewable shares are synthetic assumptions. 1R1C,
space-heating only. Verifies control and KPI logic; not TRL 7 evidence.
"""

from __future__ import annotations

from .config import load_config
from .scenario import ScenarioDef
from .simulator import Simulator, run_simulation

__all__ = ["load_config", "ScenarioDef", "Simulator", "run_simulation"]
__version__ = "0.1.0"
