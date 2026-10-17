"""Summary statistics and analysis for dispatch data."""

from __future__ import annotations

import csv
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def format_ts(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def generate_summary(dispatches: list[dict[str, Any]]) -> dict[str, Any]:
    """Generate summary statistics for dispatches."""
    if not dispatches:
        return {
            "total_dispatches": 0,
            "by_action": {},
            "by_priority": {},
            "by_audience": {},
            "cells_affected": 0,
            "with_water_source": 0,
            "generated_at": format_ts(datetime.now(timezone.utc)),
        }
    
    total = len(dispatches)
    by_action = Counter(d["action"] for d in dispatches)
    by_priority = Counter(d["priority"] for d in dispatches)
    
    all_audiences = []
    for d in dispatches:
        all_audiences.extend(d["audiences"])
    by_audience = Counter(all_audiences)
    
    cells_affected = len(set(d["cell_id"] for d in dispatches))
    with_water_source = sum(1 for d in dispatches if d["water_source"] is not None)
    
    return {
        "total_dispatches": total,
        "by_action": dict(by_action),
        "by_priority": dict(by_priority),
        "by_audience": dict(by_audience),
        "cells_affected": cells_affected,
        "with_water_source": with_water_source,
        "without_water_source": total - with_water_source,
        "generated_at": format_ts(datetime.now(timezone.utc)),
    }


def generate_risk_distribution(dispatches: list[dict[str, Any]]) -> dict[str, Any]:
    """Analyze risk level distribution from dispatch rationales."""
    if not dispatches:
        return {"critical": 0, "high": 0, "moderate": 0, "low": 0}
    
    # Extract risk level from action (DISPATCH = critical, SMS_WARN/REWET = high)
    critical = sum(1 for d in dispatches if d["action"] == "DISPATCH")
    high = sum(1 for d in dispatches if d["action"] in ["SMS_WARN", "REWET"])
    total = len(dispatches)
    
    return {
        "critical": critical,
        "high": high,
        "moderate": 0,  # No action for moderate
        "low": total - critical - high,
        "total": total,
    }


def export_to_csv(dispatches: list[dict[str, Any]], output_path: Path) -> None:
    """Export dispatches to CSV file for analysis."""
    if not dispatches:
        output_path.write_text("dispatch_id,cell_id,ts,action,priority,lat,lon,audiences,water_source_kind\n", encoding="utf-8")
        return
    
    fieldnames = [
        "dispatch_id", "cell_id", "ts", "action", "priority",
        "lat", "lon", "audiences", "water_source_kind", "water_source_distance_km"
    ]
    
    rows = []
    for d in dispatches:
        row = {
            "dispatch_id": d["dispatch_id"],
            "cell_id": d["cell_id"],
            "ts": d["ts"],
            "action": d["action"],
            "priority": d["priority"],
            "lat": d["target"]["lat"],
            "lon": d["target"]["lon"],
            "audiences": ",".join(d["audiences"]),
            "water_source_kind": d["water_source"]["kind"] if d["water_source"] else "N/A",
            "water_source_distance_km": d["water_source"]["distance_km"] if d["water_source"] else "N/A",
        }
        rows.append(row)
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def generate_incident_timeline(dispatches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Generate timeline of incidents sorted by timestamp."""
    sorted_dispatches = sorted(dispatches, key=lambda d: d["ts"])
    
    timeline = []
    for d in sorted_dispatches:
        timeline.append({
            "ts": d["ts"],
            "dispatch_id": d["dispatch_id"],
            "cell_id": d["cell_id"],
            "action": d["action"],
            "priority": d["priority"],
            "audiences": d["audiences"],
        })
    
    return timeline
