"""
Audit log — a timestamped record of every signal, decision, command and outcome.

This is the challenge's "regulator-ready evidence": in the pilot the same schema
serialises to a persistent audit store.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

# categories
SIGNAL = "signal"       # an operator/network event was received/activated
DECISION = "decision"   # accept / partial / reject
COMMAND = "command"     # a control command issued to a substation
OUTCOME = "outcome"     # measured result / restoration


@dataclass
class AuditRecord:
    timestamp: str
    hour: float
    category: str
    actor: str
    message: str
    building_id: str = ""
    values: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "hour": round(self.hour, 3),
            "category": self.category,
            "actor": self.actor,
            "message": self.message,
            "building_id": self.building_id,
            "values": self.values,
        }


class AuditLog:
    def __init__(self) -> None:
        self.records: List[AuditRecord] = []

    def add(self, timestamp: str, hour: float, category: str, actor: str,
            message: str, building_id: str = "", values: Dict[str, Any] | None = None) -> None:
        self.records.append(AuditRecord(
            timestamp=timestamp, hour=hour, category=category, actor=actor,
            message=message, building_id=building_id, values=values or {},
        ))

    def to_list(self) -> List[Dict[str, Any]]:
        return [r.to_dict() for r in self.records]
