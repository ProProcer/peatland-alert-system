"""Deterministic dispatch policy: risk → actions (schema 1.0)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from c_agent import messages
from c_agent.state_store import LEVEL_RANK, StateStore, format_ts, parse_ts
from c_agent.water import DEFAULT_MAX_WATER_KM, nearest_water_source

# rewriter(action, context, template_messages) -> messages; see c_agent/llm.py
Rewriter = Callable[[str, dict[str, Any], dict[str, dict[str, str]]], dict[str, dict[str, str]]]

ALL_AUDIENCES = ("manggala_agni", "mpa", "bpbd", "brgm", "leadership")


def _phrase(
    rewriter: Rewriter | None,
    action: str,
    ctx: dict[str, Any],
    template: dict[str, dict[str, str]],
) -> dict[str, dict[str, str]]:
    return template if rewriter is None else rewriter(action, ctx, template)


def parse_cell_id(cell_id: str) -> tuple[float, float]:
    lat_s, lon_s = cell_id.split("_", 1)
    return float(lat_s), float(lon_s)


def cells_adjacent(a: str, b: str) -> bool:
    lat1, lon1 = parse_cell_id(a)
    lat2, lon2 = parse_cell_id(b)
    dlat = abs(lat1 - lat2)
    dlon = abs(lon1 - lon2)
    return (abs(dlat - 0.1) < 1e-9 and dlon < 1e-9) or (abs(dlon - 0.1) < 1e-9 and dlat < 1e-9)


def cluster_adjacent(cell_ids: list[str]) -> list[list[str]]:
    remaining = set(cell_ids)
    clusters: list[list[str]] = []
    while remaining:
        seed = min(remaining)
        stack = [seed]
        component: list[str] = []
        remaining.remove(seed)
        while stack:
            current = stack.pop()
            component.append(current)
            neighbors = [other for other in list(remaining) if cells_adjacent(current, other)]
            for neighbor in neighbors:
                remaining.remove(neighbor)
                stack.append(neighbor)
        clusters.append(sorted(component))
    return sorted(clusters, key=lambda group: group[0])


def latest_features_by_cell(features: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_cell: dict[str, dict[str, Any]] = {}
    for row in features:
        prior = by_cell.get(row["cell_id"])
        if prior is None or parse_ts(row["ts"]) >= parse_ts(prior["ts"]):
            by_cell[row["cell_id"]] = row
    return by_cell


def select_risk_per_cell(risk_rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in risk_rows:
        grouped.setdefault(row["cell_id"], []).append(row)

    selected: dict[str, dict[str, Any]] = {}
    for cell_id, rows in grouped.items():
        selected[cell_id] = max(
            rows,
            key=lambda row: (
                LEVEL_RANK[row["risk_level"]],
                float(row["risk_score"]),
                -int(row["horizon_h"]),
            ),
        )
    return selected


def falling_deep_moisture(feature: dict[str, Any] | None) -> bool:
    if feature is None:
        return False
    delta = feature["derived"].get("sm_27_81_delta_7d")
    return delta is not None and float(delta) < 0


def _context(
    cell_id: str,
    risk: dict[str, Any],
    feature: dict[str, Any],
    target: dict[str, float],
    cluster_cell_ids: list[str],
    water_source: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "cell_id": cell_id,
        "lat": target["lat"],
        "lon": target["lon"],
        "risk_score": risk["risk_score"],
        "risk_level": risk["risk_level"],
        "horizon_h": risk["horizon_h"],
        "days_since_rain": feature["derived"].get("days_since_rain"),
        "sm_27_81": feature["weather"].get("sm_27_81"),
        "sm_27_81_delta_7d": feature["derived"].get("sm_27_81_delta_7d"),
        "top_factors": risk.get("top_factors", []),
        "cluster_size": len(cluster_cell_ids),
        "cluster_cell_ids": list(cluster_cell_ids),
        "water_source": water_source,
    }


def _base_record(
    *,
    dispatch_id: str,
    cell_id: str,
    ts: str,
    action: str,
    priority: int,
    target: dict[str, float],
    audiences: list[str],
    message_map: dict[str, dict[str, str]],
    rationale: str,
    water_source: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "dispatch_id": dispatch_id,
        "cell_id": cell_id,
        "ts": ts,
        "action": action,
        "priority": priority,
        "target": {"lat": target["lat"], "lon": target["lon"]},
        "audiences": audiences,
        "messages": {name: message_map[name] for name in audiences},
        "water_source": water_source,
        "rationale": rationale,
        "status": "PENDING",
    }


def cluster_target(cell_ids: list[str], features_by_cell: dict[str, dict[str, Any]]) -> dict[str, float]:
    lats = [features_by_cell[cid]["lat"] for cid in cell_ids]
    lons = [features_by_cell[cid]["lon"] for cid in cell_ids]
    return {"lat": round(sum(lats) / len(lats), 2), "lon": round(sum(lons) / len(lons), 2)}


def build_critical_records(
    state: StateStore,
    cluster: list[str],
    selected: dict[str, dict[str, Any]],
    features_by_cell: dict[str, dict[str, Any]],
    when: datetime,
    water_candidates: list[dict[str, Any]],
    *,
    max_water_km: float | None = DEFAULT_MAX_WATER_KM,
    rewriter: Rewriter | None = None,
) -> list[dict[str, Any]]:
    primary = max(cluster, key=lambda cid: (LEVEL_RANK[selected[cid]["risk_level"]], selected[cid]["risk_score"], -selected[cid]["horizon_h"], cid))
    risk = selected[primary]
    feature = features_by_cell[primary]
    target = cluster_target(cluster, features_by_cell)
    water = nearest_water_source(target, water_candidates, max_water_km)
    ctx = _context(primary, risk, feature, target, cluster, water)
    ts = format_ts(when)
    records = [
        _base_record(
            dispatch_id=state.allocate_dispatch_id(when),
            cell_id=primary,
            ts=ts,
            action="DISPATCH",
            priority=1,
            target=target,
            audiences=list(ALL_AUDIENCES),
            message_map=_phrase(rewriter, "DISPATCH", ctx, messages.critical_messages(ctx)),
            rationale=messages.critical_rationale(ctx),
            water_source=water,
        )
    ]
    if len(cluster) >= 2:
        records.append(
            _base_record(
                dispatch_id=state.allocate_dispatch_id(when),
                cell_id=primary,
                ts=ts,
                action="BRIEF",
                priority=2,
                target=target,
                audiences=["leadership"],
                message_map=_phrase(rewriter, "BRIEF", ctx, messages.brief_messages(ctx)),
                rationale=messages.brief_rationale(ctx),
                water_source=water,
            )
        )
    return records


def build_high_records(
    state: StateStore,
    cell_id: str,
    risk: dict[str, Any],
    feature: dict[str, Any],
    when: datetime,
    water_candidates: list[dict[str, Any]],
    *,
    max_water_km: float | None = DEFAULT_MAX_WATER_KM,
    rewriter: Rewriter | None = None,
) -> list[dict[str, Any]]:
    target = {"lat": feature["lat"], "lon": feature["lon"]}
    water = nearest_water_source(target, water_candidates, max_water_km)
    ctx = _context(cell_id, risk, feature, target, [cell_id], water)
    ts = format_ts(when)
    return [
        _base_record(
            dispatch_id=state.allocate_dispatch_id(when),
            cell_id=cell_id,
            ts=ts,
            action="SMS_WARN",
            priority=2,
            target=target,
            audiences=["mpa"],
            message_map=_phrase(rewriter, "SMS_WARN", ctx, messages.sms_warn_messages(ctx)),
            rationale=messages.high_rationale(ctx, "SMS_WARN"),
            water_source=water,
        ),
        _base_record(
            dispatch_id=state.allocate_dispatch_id(when),
            cell_id=cell_id,
            ts=ts,
            action="REWET",
            priority=3,
            target=target,
            audiences=["brgm"],
            message_map=_phrase(rewriter, "REWET", ctx, messages.rewet_messages(ctx)),
            rationale=messages.high_rationale(ctx, "REWET"),
            water_source=water,
        ),
    ]


def decide(
    features: list[dict[str, Any]],
    risk_rows: list[dict[str, Any]],
    state: StateStore,
    *,
    now: datetime | None = None,
    water_candidates: list[dict[str, Any]] | None = None,
    max_water_km: float | None = DEFAULT_MAX_WATER_KM,
    rewriter: Rewriter | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Produce (active dispatches, newly minted this run)."""
    when = now or datetime.now(timezone.utc)
    candidates = water_candidates if water_candidates is not None else []
    features_by_cell = latest_features_by_cell(features)
    selected = select_risk_per_cell(risk_rows)
    output: list[dict[str, Any]] = []
    created: list[dict[str, Any]] = []
    handled: set[str] = set()

    critical_ids = sorted(cid for cid, row in selected.items() if row["risk_level"] == "CRITICAL" and cid in features_by_cell)
    for cluster in cluster_adjacent(critical_ids):
        decision, reused = state.should_emit(cluster, "CRITICAL", when)
        if decision == "reuse":
            output.extend(reused)
        elif decision == "new":
            records = build_critical_records(
                state, cluster, selected, features_by_cell, when, candidates,
                max_water_km=max_water_km, rewriter=rewriter,
            )
            state.remember(cluster, records, "CRITICAL", cluster[0])
            output.extend(records)
            created.extend(records)
        else:
            state.clear_cells(cluster)
        handled.update(cluster)

    for cell_id, risk in sorted(selected.items()):
        if cell_id in handled or cell_id not in features_by_cell:
            continue
        feature = features_by_cell[cell_id]
        if risk["risk_level"] == "HIGH" and falling_deep_moisture(feature):
            decision, reused = state.should_emit([cell_id], "HIGH", when)
            if decision == "reuse":
                output.extend(reused)
            elif decision == "new":
                records = build_high_records(
                    state, cell_id, risk, feature, when, candidates,
                    max_water_km=max_water_km, rewriter=rewriter,
                )
                state.remember([cell_id], records, "HIGH", cell_id)
                output.extend(records)
                created.extend(records)
            else:
                state.clear_cells([cell_id])
        elif state.get(cell_id) is not None:
            state.clear_cells([cell_id])

    output.sort(key=lambda row: (row["priority"], row["cell_id"], row["dispatch_id"]))
    return output, created


def dispatch_timestamp(risk_ts: str, offset_minutes: int = 5) -> datetime:
    return parse_ts(risk_ts) + timedelta(minutes=offset_minutes)
