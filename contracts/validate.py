"""Validate playbook handoffs without importing any role's implementation."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
import math
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = Path(__file__).resolve().parent
KINDS = {"features": "features.json", "risk": "risk.json", "dispatch": "dispatch.json", "cells": "cells.geojson"}


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_json(path: Path) -> Any:
    def invalid_constant(value: str) -> None:
        raise ValueError(f"non-finite JSON number: {value}")

    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object, parse_constant=invalid_constant)


def _finite(value: Any) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("non-finite numeric value")
    if isinstance(value, dict):
        for child in value.values():
            _finite(child)
    elif isinstance(value, list):
        for child in value:
            _finite(child)


def cell_center(cell_id: str) -> tuple[float, float]:
    lat, lon = (float(part) for part in cell_id.split("_"))
    if not (-90 < lat < 90 and -180 < lon < 180):
        raise ValueError(f"cell center out of range: {cell_id}")
    if cell_id != f"{lat:.2f}_{lon:.2f}":
        raise ValueError(f"non-canonical cell ID: {cell_id}")
    for value in (lat, lon):
        if not math.isclose((value - 0.05) / 0.1, round((value - 0.05) / 0.1), abs_tol=1e-7):
            raise ValueError(f"cell center must be on .x5: {cell_id}")
    return lat, lon


def risk_level(score: float) -> str:
    if score < 0.35:
        return "LOW"
    if score < 0.60:
        return "MODERATE"
    if score < 0.80:
        return "HIGH"
    return "CRITICAL"


def validate_payload(kind: str, payload: Any) -> None:
    schema = load_json(CONTRACTS / f"{kind}.schema.json")
    Draft202012Validator.check_schema(schema)
    errors = list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(payload))
    if errors:
        error = errors[0]
        location = "/".join(str(part) for part in error.absolute_path) or "<root>"
        raise ValueError(f"{kind} at {location}: {error.message}")
    _finite(payload)
    rows = payload["features"] if kind == "cells" else payload
    seen: set[tuple[Any, ...]] = set()
    for row in rows:
        if kind != "cells":
            datetime.fromisoformat(row["ts"].replace("Z", "+00:00"))
        cell_id = row["properties"]["cell_id"] if kind == "cells" else row["cell_id"]
        lat, lon = cell_center(cell_id)
        key = (cell_id,)
        if kind == "features":
            key = (cell_id, row["ts"])
            if not (math.isclose(row["lat"], lat, abs_tol=1e-8) and math.isclose(row["lon"], lon, abs_tol=1e-8)):
                raise ValueError(f"coordinates do not match cell_id: {cell_id}")
            if all(value is None for value in row["weather"].values()):
                raise ValueError(f"all-null weather: {cell_id}")
        elif kind == "risk":
            key = (cell_id, row["horizon_h"])
            if row["risk_level"] != risk_level(row["risk_score"]):
                raise ValueError(f"risk_level does not match risk_score: {cell_id}")
        elif kind == "dispatch":
            key = (row["dispatch_id"],)
            missing = set(row["audiences"]) - row["messages"].keys()
            if missing:
                raise ValueError(f"missing audience messages: {sorted(missing)}")
        elif kind == "cells":
            rings = row["geometry"]["coordinates"]
            expected = {(round(lon + dx, 7), round(lat + dy, 7)) for dx in (-0.05, 0.05) for dy in (-0.05, 0.05)}
            ring = rings[0]
            actual = {(round(x, 7), round(y, 7)) for x, y in ring[:-1]}
            if len(rings) != 1 or len(ring) != 5 or ring[0] != ring[-1] or actual != expected:
                raise ValueError(f"geometry must be the closed 0.1-degree square in [lon, lat] order: {cell_id}")
            for start, end in zip(ring, ring[1:]):
                if not ((start[0] == end[0]) != (start[1] == end[1])):
                    raise ValueError(f"cell ring has a diagonal or repeated edge: {cell_id}")
        if key in seen:
            raise ValueError(f"duplicate {kind} record: {key}")
        seen.add(key)


def validate_file(kind: str, path: Path) -> Any:
    payload = load_json(path)
    validate_payload(kind, payload)
    return payload


def validate_directory(directory: Path) -> None:
    feeds = {kind: validate_file(kind, directory / name) for kind, name in KINDS.items()}
    feature_cells = {row["cell_id"] for row in feeds["features"]}
    map_cells = {row["properties"]["cell_id"] for row in feeds["cells"]["features"]}
    risk_cells = {row["cell_id"] for row in feeds["risk"]}
    if feature_cells != map_cells or risk_cells != feature_cells:
        raise ValueError("features, cells and risk must cover the same cell IDs")
    latest = {cell: max((row["ts"] for row in feeds["features"] if row["cell_id"] == cell),
                       key=lambda value: datetime.fromisoformat(value.replace("Z", "+00:00"))) for cell in feature_cells}
    for cell in feature_cells:
        predictions = [row for row in feeds["risk"] if row["cell_id"] == cell]
        if {row["horizon_h"] for row in predictions} != {24, 48, 72}:
            raise ValueError(f"missing risk horizon for {cell}")
        if any(row["ts"] != latest[cell] for row in predictions):
            raise ValueError(f"risk timestamp is not the latest feature timestamp for {cell}")
    for row in feeds["dispatch"]:
        if row["cell_id"] not in feature_cells:
            raise ValueError(f"dispatch references unknown cell: {row['cell_id']}")


def validate_repository() -> int:
    count = 0
    for kind in KINDS:
        validate_file(kind, CONTRACTS / "examples" / KINDS[kind])
        count += 1
    validate_directory(CONTRACTS / "examples")
    fixtures = [("features", "a_data/mock_output.json"), ("cells", "a_data/fixtures/cells.geojson"),
                ("risk", "b_model/mock_output.json"), ("dispatch", "c_agent/mock_output.json"),
                ("risk", "d_frontend/mock_output.json"), ("dispatch", "e_platform/mock_output.json")]
    fixtures += [(kind, f"d_frontend/mocks/{name}") for kind, name in KINDS.items()]
    fixtures += [(kind, f"data/processed/{name}") for kind, name in KINDS.items() if (ROOT / "data/processed" / name).exists()]
    for kind, path in fixtures:
        validate_file(kind, ROOT / path)
        count += 1
    validate_directory(ROOT / "d_frontend/mocks")
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", type=Path)
    parser.add_argument("--kind", choices=KINDS)
    parser.add_argument("--data-dir", type=Path)
    args = parser.parse_args()
    if args.data_dir and (args.path or args.kind):
        parser.error("use --data-dir or --kind plus a path")
    if bool(args.path) != bool(args.kind):
        parser.error("file validation requires both --kind and a path")
    try:
        if args.data_dir:
            validate_directory(args.data_dir)
            print(f"Validated all handoffs in {args.data_dir}")
        elif args.path:
            validate_file(args.kind, args.path)
            print(f"Validated {args.kind}: {args.path}")
        else:
            print(f"Validated {validate_repository()} contract fixtures / processed files")
    except (ValueError, OSError) as error:
        parser.exit(1, f"Validation failed: {error}\n")


if __name__ == "__main__":
    main()
