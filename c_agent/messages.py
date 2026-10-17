"""Deterministic bilingual message templates. Numbers come only from structured fields."""

from __future__ import annotations

from typing import Any


def _fmt_num(value: Any, digits: int = 2) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, int):
        return str(value)
    return f"{float(value):.{digits}f}"


def _coord(lat: float, lon: float) -> str:
    return f"{_fmt_num(lat)}, {_fmt_num(lon)}"


def _water_blurb(ctx: dict[str, Any]) -> tuple[str, str]:
    water = ctx.get("water_source")
    if not water:
        return (
            "sumber air belum tersedia",
            "water-source data is unavailable",
        )
    where = _coord(water["lat"], water["lon"])
    dist = _fmt_num(water["distance_km"], 3)
    kind = water["kind"]
    return (
        f"sumber air terdekat: {kind} di {where} ({dist} km)",
        f"nearest water source: {kind} at {where} ({dist} km)",
    )


def critical_messages(ctx: dict[str, Any]) -> dict[str, dict[str, str]]:
    where = _coord(ctx["lat"], ctx["lon"])
    score = _fmt_num(ctx["risk_score"])
    horizon = ctx["horizon_h"]
    days = _fmt_num(ctx.get("days_since_rain"), 0)
    sm = _fmt_num(ctx.get("sm_27_81"))
    water_id, water_en = _water_blurb(ctx)
    return {
        "manggala_agni": {
            "id": f"Simulasi: siapkan patroli ke {where}; risiko {score} dalam {horizon} jam; {water_id}.",
            "en": f"Simulation: prepare a patrol to {where}; risk {score} over {horizon} hours; {water_en}.",
        },
        "mpa": {
            "id": f"Simulasi: warga di sekitar {where} diminta waspada dan tidak membakar lahan.",
            "en": f"Simulation: communities near {where} should remain alert and avoid land burning.",
        },
        "bpbd": {
            "id": f"Simulasi: koordinasikan kesiapsiagaan pada {where}; {water_id}.",
            "en": f"Simulation: coordinate readiness at {where}; {water_en}.",
        },
        "brgm": {
            "id": f"Simulasi: tinjau kebutuhan pembasahan pada {where}; kelembapan gambut dalam {sm} m³/m³.",
            "en": f"Simulation: assess rewetting needs at {where}; deep soil moisture is {sm} m³/m³.",
        },
        "leadership": {
            "id": (
                f"Simulasi: {ctx['cluster_size']} sel kritis (horizon {horizon} jam); "
                f"{days} hari tanpa hujan ≥1 mm."
            ),
            "en": (
                f"Simulation: {ctx['cluster_size']} critical cell(s) at the {horizon}-hour horizon; "
                f"{days} day(s) without ≥1 mm rain."
            ),
        },
    }


def brief_messages(ctx: dict[str, Any]) -> dict[str, dict[str, str]]:
    cells = ", ".join(ctx["cluster_cell_ids"])
    return {
        "leadership": {
            "id": (
                f"Simulasi: gugus {ctx['cluster_size']} sel kritis ({cells}); "
                f"titik koordinasi {_coord(ctx['lat'], ctx['lon'])}."
            ),
            "en": (
                f"Simulation: cluster of {ctx['cluster_size']} critical cells ({cells}); "
                f"coordination point {_coord(ctx['lat'], ctx['lon'])}."
            ),
        }
    }


def sms_warn_messages(ctx: dict[str, Any]) -> dict[str, dict[str, str]]:
    where = _coord(ctx["lat"], ctx["lon"])
    score = _fmt_num(ctx["risk_score"])
    delta = _fmt_num(ctx.get("sm_27_81_delta_7d"))
    return {
        "mpa": {
            "id": (
                f"Simulasi: peringatan SMS — risiko {score} di {where}; "
                f"kelembapan dalam turun {delta} m³/m³ (7 hari)."
            ),
            "en": (
                f"Simulation: SMS warning — risk {score} at {where}; "
                f"deep soil moisture fell {delta} m³/m³ over 7 days."
            ),
        }
    }


def rewet_messages(ctx: dict[str, Any]) -> dict[str, dict[str, str]]:
    where = _coord(ctx["lat"], ctx["lon"])
    sm = _fmt_num(ctx.get("sm_27_81"))
    delta = _fmt_num(ctx.get("sm_27_81_delta_7d"))
    return {
        "brgm": {
            "id": (
                f"Simulasi: tinjau pembasahan di {where}; "
                f"sm_27_81={sm} m³/m³, delta 7 hari={delta}."
            ),
            "en": (
                f"Simulation: assess rewetting at {where}; "
                f"sm_27_81={sm} m³/m³, 7-day delta={delta}."
            ),
        }
    }


def critical_rationale(ctx: dict[str, Any]) -> str:
    days = _fmt_num(ctx.get("days_since_rain"), 0)
    sm = _fmt_num(ctx.get("sm_27_81"))
    delta = _fmt_num(ctx.get("sm_27_81_delta_7d"))
    factors = ", ".join(f"{item['feature']}={_fmt_num(item['contribution'])}" for item in ctx.get("top_factors", [])[:3])
    water_id, _ = _water_blurb(ctx)
    return (
        f"Risk {_fmt_num(ctx['risk_score'])} for {ctx['horizon_h']}h on {ctx['cell_id']}; "
        f"{days} days since rain; deep soil moisture {sm} (Δ7d {delta}). "
        f"Top factors: {factors}. {water_id.capitalize()}. Simulated alert only."
    )


def high_rationale(ctx: dict[str, Any], action: str) -> str:
    return (
        f"{action} for HIGH risk {_fmt_num(ctx['risk_score'])} at {ctx['horizon_h']}h on {ctx['cell_id']}; "
        f"sm_27_81_delta_7d={_fmt_num(ctx.get('sm_27_81_delta_7d'))} (falling). Simulated alert only."
    )


def brief_rationale(ctx: dict[str, Any]) -> str:
    return (
        f"BRIEF for CRITICAL cluster of {ctx['cluster_size']} cells "
        f"({', '.join(ctx['cluster_cell_ids'])}); target {_coord(ctx['lat'], ctx['lon'])}. "
        f"Simulated alert only."
    )
