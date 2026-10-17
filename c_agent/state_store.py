"""Persisted incident state for dedupe, cooldown and escalation."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

POLICY_VERSION = "2-high-critical-dispatch"

LEVEL_RANK = {"LOW": 0, "MODERATE": 1, "HIGH": 2, "CRITICAL": 3}


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def format_ts(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class StateStore:
    def __init__(self, path: Path, cooldown_hours: float = 6.0) -> None:
        self.path = path
        self.cooldown = timedelta(hours=cooldown_hours)
        self._data: dict[str, Any] = {"next_seq": 1, "incidents": {}}
        if path.exists():
            loaded = json.loads(path.read_text(encoding="utf-8"))
            self._data["next_seq"] = int(loaded.get("next_seq", 1))
            self._data["incidents"] = dict(loaded.get("incidents", {}))
            self._data["water_context"] = loaded.get("water_context")

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(self._data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.path)

    def set_water_context(self, context: dict) -> None:
        """Rebuild incident messages when the source catalogue or search radius changes."""
        if self._data.get('water_context') != context:
            self._data['incidents'] = {}
            self._data['water_context'] = context

    def allocate_dispatch_id(self, when: datetime) -> str:
        seq = int(self._data["next_seq"])
        self._data["next_seq"] = seq + 1
        return f"d_{when.strftime('%Y%m%d')}_{seq:04d}"

    def get(self, cell_id: str) -> dict[str, Any] | None:
        return self._data["incidents"].get(cell_id)

    def clear_cells(self, cell_ids: list[str]) -> None:
        for cell_id in cell_ids:
            self._data["incidents"].pop(cell_id, None)

    def remember(
        self,
        cell_ids: list[str],
        records: list[dict[str, Any]],
        risk_level: str,
        cluster_key: str,
    ) -> None:
        entry = {
            "policy_version": POLICY_VERSION,
            "cell_ids": sorted(cell_ids),
            "risk_level": risk_level,
            "cluster_key": cluster_key,
            "ts": records[0]["ts"],
            "records": deepcopy(records),
        }
        for cell_id in cell_ids:
            self._data["incidents"][cell_id] = deepcopy(entry)

    def should_emit(self, cell_ids: list[str], risk_level: str, when: datetime) -> tuple[str, list[dict[str, Any]]]:
        """Return (decision, records).

        decision is one of: ``new``, ``reuse``, ``suppress``.
        """
        present = [item for cell_id in cell_ids if (item := self.get(cell_id)) is not None]
        if not present:
            return "new", []

        if any(item.get('policy_version') != POLICY_VERSION for item in present):
            return "new", []
        if len(present) != len(cell_ids) or any(item.get('cell_ids') != sorted(cell_ids) for item in present):
            return "new", []

        max_level = max(LEVEL_RANK[item["risk_level"]] for item in present)
        new_level = LEVEL_RANK[risk_level]
        if new_level > max_level:
            return "new", []
        if new_level < max_level:
            return "new", []

        freshest = max(present, key=lambda item: parse_ts(item["ts"]))
        if when - parse_ts(freshest["ts"]) < self.cooldown:
            reused: list[dict[str, Any]] = []
            seen: set[str] = set()
            for item in present:
                for record in item["records"]:
                    if record["dispatch_id"] not in seen:
                        reused.append(deepcopy(record))
                        seen.add(record["dispatch_id"])
            return "reuse", reused

        return "new", []
