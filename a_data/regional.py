"""Build a spatially spread 40-cell Kalimantan bundle with centers on mapped peat."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from xml.sax.saxutils import escape

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import requests
import shapely
from shapely.geometry import mapping, shape
from shapely.ops import transform
from shapely.strtree import STRtree

from a_data.assemble import assemble
from a_data.common import FEATURES, ROOT, sha256, utc_now, write_json, write_parquet
from a_data.geography import TO_AREA, load_boundary, polygonal
from a_data.validate_real import validate
from a_data.weather import WeatherBudgetExceeded, WeatherClient, parse_response

BUNDLE = "regional_40"
PER_PROVINCE = 8


def peat_geometries(peat_path: Path):
    source = json.loads(peat_path.read_text(encoding="utf-8-sig"))
    return [polygonal(shape(feature["geometry"])) for feature in source["features"]]


def center_coverage(cells: pd.DataFrame, polygons: list) -> np.ndarray:
    pairs = STRtree(polygons).query(shapely.points(cells["lon"].to_numpy(), cells["lat"].to_numpy()), predicate="within")
    covered = np.zeros(len(cells), dtype=bool)
    covered[np.unique(pairs[0])] = True
    return covered


def spread_indices(candidates: pd.DataFrame, count: int) -> list[int]:
    """Deterministic farthest-point sampling in the regional equal-area CRS.

    Seed nearest the candidate centroid; then maximize distance to the closest
    selected point. Neither fire labels nor historical outcomes enter selection.
    """
    if len(candidates) < count:
        raise ValueError(f"Only {len(candidates)} candidates; need {count}")
    points = [transform(TO_AREA, shape({"type": "Point", "coordinates": [row.lon, row.lat]}))
              for row in candidates.itertuples()]
    xy = np.array([[point.x, point.y] for point in points])
    seed = int(np.argmin(np.sum((xy - xy.mean(axis=0)) ** 2, axis=1)))
    chosen = [seed]
    distance = np.full(len(xy), np.inf)
    while len(chosen) < count:
        distance = np.minimum(distance, np.sum((xy - xy[chosen[-1]]) ** 2, axis=1))
        distance[chosen] = -np.inf
        chosen.append(int(np.argmax(distance)))
    return chosen


def select_cells(output_dir: Path) -> dict:
    peat_path = ROOT / "data/raw/Indonesia_Peat_Lands.geojson"
    cells = pd.read_parquet(output_dir / "cells.parquet").sort_values("cell_id").reset_index(drop=True)
    polygons = peat_geometries(peat_path)
    region, provinces, boundary = load_boundary(output_dir / "cache")
    on_peat = center_coverage(cells, polygons)
    in_region = shapely.contains_xy(region, cells["lon"].to_numpy(), cells["lat"].to_numpy())
    eligible = cells[on_peat & in_region].copy()
    if eligible["province"].nunique() != 5:
        raise ValueError("Expected eligible centers in all five Kalimantan provinces")
    selection_path = output_dir / BUNDLE / "selection.json"
    if selection_path.exists():
        selection = json.loads(selection_path.read_text(encoding="utf-8"))
        valid_ids = set(eligible["cell_id"])
        if len(selection["cell_ids"]) != 40 or not set(selection["cell_ids"]).issubset(valid_ids):
            raise ValueError("Existing selection differs from current eligible geometry; review before replacing")
        if selection["peat_source_sha256"] != sha256(peat_path):
            raise ValueError("Peat source changed since this selection was frozen")
        if selection["grid_sha256"] != sha256(output_dir / "cells.parquet"):
            raise ValueError("Grid changed since this selection was frozen")
        return selection
    picked = []
    for province, group in eligible.groupby("province", sort=True):
        group = group.sort_values("cell_id").reset_index(drop=True)
        chosen = group.iloc[spread_indices(group, PER_PROVINCE)].copy()
        chosen["selection_rank_in_province"] = np.arange(1, PER_PROVINCE + 1)
        picked.append(chosen)
    selected = pd.concat(picked, ignore_index=True)
    cached_ids = {"_".join(path.name.split("_")[:2]) for path in (output_dir / "cache/weather").glob("*.json")
                  if path.name != "usage_ledger.json"}
    records = selected.to_dict("records")
    for record in records:
        record["polygon_ids"] = list(record["polygon_ids"])
        record["center_on_mapped_peat"] = True
        record["weather_cached_at_selection"] = record["cell_id"] in cached_ids
    new_count = sum(not record["weather_cached_at_selection"] for record in records)
    selection = {"created_at": utc_now(), "is_mock": False, "schema_version": "1.0",
                 "scope": "40 peat-centered cells across all five Indonesian Kalimantan provinces",
                 "cell_count": len(selected), "cells_per_province": PER_PROVINCE,
                 "eligible_center_count": len(eligible),
                 "eligible_by_province": {str(k): int(v) for k, v in eligible.groupby("province").size().items()},
                 "cell_ids": list(selected["cell_id"]), "cells": records,
                 "selection_method": "Per province, start nearest candidate centroid, then farthest-point sampling in regional LAEA; deterministic cell_id tie order; no fire outcomes used.",
                 "center_rule": "Strictly within the supplied peat geometry and Indonesian Kalimantan boundary; original 0.1-degree grid and >=0.05 peat fraction retained.",
                 "label_definition": "Unchanged schema 1.0: nominal/high FIRMS event anywhere inside the qualifying cell during (t,t+h]. Peat-centered cells do not imply peat-only fire labels.",
                 "peat_source_sha256": sha256(peat_path), "grid_sha256": sha256(output_dir / "cells.parquet"),
                 "boundary_id": boundary["boundaryID"],
                 "cached_weather_cells_at_selection": len(selected) - new_count,
                 "new_weather_cells_at_selection": new_count,
                 "estimated_additional_weighted_calls": round(new_count * 71.4, 1)}
    write_json(selection_path, selection)
    write_json(output_dir / BUNDLE / "centers.geojson", {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": record, "geometry": {"type": "Point", "coordinates": [record["lon"], record["lat"]]}}
        for record in records]})
    preview(output_dir, selected, polygons, region, provinces)
    print(json.dumps({key: selection[key] for key in ("cell_count", "eligible_by_province", "cached_weather_cells_at_selection", "new_weather_cells_at_selection", "estimated_additional_weighted_calls")}), flush=True)
    return selection


def preview(output_dir: Path, selected: pd.DataFrame, peat: list, region, provinces) -> None:
    """Standalone SVG overview; simplified display geometry never changes areas."""
    west, south, east, north = 108.5, -4.0, 119.0, 4.7
    width, height, pad = 1060, 920, 60
    scale = min((width - 2 * pad) / (east - west), (height - 2 * pad) / (north - south))

    def position(lon, lat):
        return pad + (lon - west) * scale, pad + (north - lat) * scale

    def paths(geometry):
        if geometry.is_empty:
            return []
        if geometry.geom_type == "Polygon":
            parts = []
            for ring in (geometry.exterior, *geometry.interiors):
                points = [position(lon, lat) for lon, lat in ring.coords]
                parts.append("M" + " L".join(f"{x:.2f},{y:.2f}" for x, y in points) + " Z")
            return [" ".join(parts)]
        if hasattr(geometry, "geoms"):
            return [part for child in geometry.geoms for part in paths(child)]
        return []

    palette = {"Central Kalimantan": "#2563eb", "East Kalimantan": "#e11d48", "North Kalimantan": "#7c3aed",
               "South Kalimantan": "#ea580c", "West Kalimantan": "#0891b2"}
    pieces = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
              '<rect width="100%" height="100%" fill="#f8fafc"/>',
              '<text x="30" y="28" font-family="sans-serif" font-size="20" fill="#0f172a">40 peat-centered prediction cells across Indonesian Kalimantan</text>',
              '<text x="30" y="49" font-family="sans-serif" font-size="12" fill="#475569">Colored points: 8 per province. Green: supplied peat geometry. Gray rings: previous 33-cell subset.</text>']
    for feature in provinces:
        for path in paths(shape(feature["geometry"]).simplify(.008, preserve_topology=True)):
            pieces.append(f'<path d="{path}" fill="#eef2f6" fill-rule="evenodd" stroke="#94a3b8" stroke-width="1"/>')
    for geometry in peat:
        if geometry.envelope.intersects(region.envelope) and geometry.intersects(region):
            for path in paths(geometry.intersection(region).simplify(.003, preserve_topology=True)):
                pieces.append(f'<path d="{path}" fill="#86b99a" fill-rule="evenodd" stroke="none"/>')
    original_scope = output_dir / "hackathon/scope.json"
    if original_scope.exists():
        original_ids = set(json.loads(original_scope.read_text())["cell_ids"])
        original_cells = pd.read_parquet(output_dir / "cells.parquet")
        for row in original_cells[original_cells["cell_id"].isin(original_ids)].itertuples():
            x, y = position(row.lon, row.lat)
            pieces.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="4" fill="none" stroke="#64748b" stroke-width="1" opacity=".7"><title>Previous {escape(row.cell_id)}</title></circle>')
    for row in selected.itertuples():
        x, y = position(row.lon, row.lat)
        title = escape(f"{row.province}: {row.cell_id}; lat={row.lat}, lon={row.lon}; peat={row.peat_fraction:.1%}")
        pieces.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="5.5" fill="{palette[row.province]}" stroke="white" stroke-width="1.5"><title>{title}</title></circle>')
    for index, (province, color) in enumerate(palette.items()):
        y = 780 + index * 22
        pieces.append(f'<circle cx="760" cy="{y}" r="5" fill="{color}"/><text x="775" y="{y + 4}" font-family="sans-serif" font-size="13" fill="#0f172a">{province}: 8 cells</text>')
    pieces.append('<text x="30" y="902" font-family="sans-serif" font-size="11" fill="#475569">Peat: supplied GeoJSON. Boundaries: geoBoundaries / OSM-Wambacher, 2017 (ODbL). Equirectangular overview, no routing.</text></svg>')
    (output_dir / BUNDLE / "selection_preview.svg").write_text("\n".join(pieces), encoding="utf-8")


def fetch_selected_weather(output_dir: Path, selection: dict, cache_only: bool = False) -> dict:
    config = json.loads((ROOT / "a_data/processing_config.json").read_text())
    start = (pd.Timestamp(config["start_date"]) - pd.Timedelta(days=30)).strftime("%Y-%m-%d")
    end = config["weather_historical_end_date"]
    client = WeatherClient(output_dir / "cache/weather", config["weather_daily_budget"])
    target = output_dir / "weather_regional_40.parquet"
    temporary = target.with_suffix(".parquet.tmp")
    writer, reports = None, []
    result = {"updated_at": utc_now(), "is_mock": False, "status": "running", "model": "icon_global",
              "start_date_with_warmup": start, "end_date": end, "expected_cells": 40, "completed_cells": 0}
    try:
        for cell in selection["cells"]:
            try:
                cached = client.fetch(cell, start, end, cache_only=cache_only)
                frame, report = parse_response(cached, cell)
            except (WeatherBudgetExceeded, requests.RequestException, FileNotFoundError, ValueError) as exc:
                result.update(status="incomplete_resumable", error=str(exc), failed_cell_id=cell["cell_id"])
                break
            frame["ts"] = frame["ts"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            write_parquet(frame, output_dir / "cache/normalized_weather" / f"{cell['cell_id']}.parquet")
            table = pa.Table.from_pandas(frame, preserve_index=False)
            if writer is None:
                writer = pq.ParquetWriter(temporary, table.schema, compression="zstd")
            writer.write_table(table)
            reports.append(report)
            result.update(updated_at=utc_now(), completed_cells=len(reports), last_cell_id=cell["cell_id"])
            write_json(output_dir / BUNDLE / "weather_progress.json", result)
            print(f"Regional weather: {cell['province']} {cell['cell_id']}; {len(reports)}/40", flush=True)
    finally:
        if writer is not None:
            writer.close()
    if len(reports) == 40:
        temporary.replace(target)
        result.update(status="complete", error=None)
    result.update(updated_at=utc_now(), cells=reports, completed_rows=sum(row["rows"] for row in reports))
    write_json(output_dir / BUNDLE / "weather_report.json", result)
    write_json(output_dir / BUNDLE / "weather_progress.json", {key: value for key, value in result.items() if key != "cells"})
    if result["status"] != "complete":
        raise RuntimeError(f"Regional download incomplete; caches retained: {result.get('error')}")
    return result


def assemble_selected(output_dir: Path, selection: dict) -> dict:
    weather_path = output_dir / "weather_regional_40.parquet"
    weather = pd.read_parquet(weather_path, columns=["cell_id"])
    if set(weather["cell_id"]) != set(selection["cell_ids"]):
        raise ValueError("Regional weather does not cover the frozen 40-cell selection")
    report = assemble(output_dir, weather_path, ROOT / "a_data/processing_config.json", BUNDLE)
    history = pd.read_parquet(output_dir / BUNDLE / "history.parquet")
    year = history[(history["ts"] >= "2025-01-01T00:00:00Z") & (history["ts"] < "2026-01-01T00:00:00Z")]
    write_parquet(year, output_dir / BUNDLE / "history_2025.parquet")
    scope = {"updated_at": utc_now(), "is_mock": False, "scope": selection["scope"], "cell_count": 40,
             "cells_by_province": {province: PER_PROVINCE for province in sorted({cell["province"] for cell in selection["cells"]})},
             "cell_ids": selection["cell_ids"], "history_rows": report["history_rows"], "history_2025_rows": len(year),
             "snapshot": report["snapshot"], "schema_version": "1.0", "model_features": 27, "horizons_h": [24, 48, 72],
             "center_rule": selection["center_rule"], "label_definition": selection["label_definition"]}
    write_json(output_dir / BUNDLE / "scope.json", scope)
    audit_event_overlap(output_dir, selection)
    return scope


def audit_event_overlap(output_dir: Path, selection: dict) -> dict:
    """Report peat-point overlap separately; do not alter the frozen labels."""
    detections = pd.read_parquet(output_dir / "firms_normalized.parquet")
    detections = detections[detections["in_scope"] & detections["in_requested_window"]
                            & detections["alert_eligible"] & detections["cell_id"].isin(selection["cell_ids"])].copy()
    peat = peat_geometries(ROOT / "data/raw/Indonesia_Peat_Lands.geojson")
    pairs = STRtree(peat).query(shapely.points(detections["longitude"].to_numpy(), detections["latitude"].to_numpy()), predicate="intersects")
    covered = np.zeros(len(detections), dtype=bool)
    covered[np.unique(pairs[0])] = True
    detections["point_on_mapped_peat"] = covered
    province_lookup = {cell["cell_id"]: cell["province"] for cell in selection["cells"]}
    detections["province"] = detections["cell_id"].map(province_lookup)

    def counts(frame):
        total, on_peat = len(frame), int(frame["point_on_mapped_peat"].sum())
        return {"nominal_high_detection_records": total, "point_on_mapped_peat": on_peat,
                "point_outside_mapped_peat": total - on_peat,
                "on_mapped_peat_percent": round(100 * on_peat / total, 2) if total else None}

    year = detections[detections["ts"].str.startswith("2025-")]
    report = {"generated_at": utc_now(), "is_mock": False, "scope": selection["scope"],
              "definition": "Detection coordinate intersects the supplied peat polygon, including its boundary.",
              "all_delivered_history": counts(detections), "calendar_2025": counts(year),
              "by_province": {province: counts(detections[detections["province"] == province]) for province in sorted(set(province_lookup.values()))},
              "note": "Detection records are not hourly training rows. This supporting audit does not change target labels, which remain cell-based under schema 1.0."}
    write_json(output_dir / BUNDLE / "peat_overlap_audit.json", report)
    return report


def audit_selection(output_dir: Path, selection: dict) -> None:
    cells = pd.DataFrame(selection["cells"])
    peat = peat_geometries(ROOT / "data/raw/Indonesia_Peat_Lands.geojson")
    region, provinces, _ = load_boundary(output_dir / "cache")
    if not center_coverage(cells, peat).all() or not shapely.contains_xy(region, cells["lon"].to_numpy(), cells["lat"].to_numpy()).all():
        raise ValueError("A selected center is outside mapped peat or the requested region")
    if cells["cell_id"].nunique() != 40 or not cells.groupby("province").size().eq(PER_PROVINCE).all():
        raise ValueError("Selection must contain eight distinct centers in each of five provinces")
    province_shapes = {feature["properties"]["shapeName"]: shape(feature["geometry"]) for feature in provinces}
    if not all(province_shapes[row.province].contains(shapely.Point(row.lon, row.lat)) for row in cells.itertuples()):
        raise ValueError("A selected center is outside its assigned province")
    report = validate(output_dir, BUNDLE, output_dir / "weather_regional_40.parquet")
    report.update(selection_checks={"all_40_centers_strictly_inside_mapped_peat": True,
                  "all_40_centers_inside_indonesian_kalimantan": True, "five_provinces_eight_cells_each": True,
                  "all_centers_inside_their_assigned_province": True,
                  "selection_uses_no_fire_outcomes": True})
    write_json(output_dir / BUNDLE / "validation_report.json", report)
    summarize_history(output_dir)


def summarize_history(output_dir: Path) -> dict:
    """Describe data using B's documented split, without ML-only dependencies."""
    bundle = output_dir / BUNDLE
    targets = [f"target_{h}h" for h in (24, 48, 72)]
    history = pd.read_parquet(bundle / "history.parquet")
    year = pd.read_parquet(bundle / "history_2025.parquet")

    def describe(frame):
        return {"rows": len(frame), "columns": len(frame.columns), "cells": int(frame["cell_id"].nunique()),
                "start": frame["ts"].min(), "end": frame["ts"].max(),
                "complete_target_rows": int(frame[targets].notna().all(axis=1).sum()),
                "feature_nulls": {column: int(frame[column].isna().sum()) for column in FEATURES},
                "target_nulls": {column: int(frame[column].isna().sum()) for column in targets},
                "target_positives": {column: int(frame[column].sum()) for column in targets}}

    complete = year.dropna(subset=targets)
    timestamps = pd.to_datetime(complete["ts"], utc=True)
    unique_hours = timestamps.sort_values().unique()
    calibration_start = unique_hours[int(len(unique_hours) * .55)]
    validation_start = unique_hours[int(len(unique_hours) * .75)]
    embargo = pd.Timedelta(hours=72)
    partitions = (complete[timestamps < calibration_start - embargo],
                  complete[(timestamps >= calibration_start) & (timestamps < validation_start - embargo)],
                  complete[timestamps >= validation_start])
    split_report = {}
    for name, frame in zip(("train", "calibration", "validation"), partitions):
        split_report[name] = describe(frame)
        split_report[name]["both_classes_all_horizons"] = all(frame[column].nunique() == 2 for column in targets)
        split_report[name]["all_null_features"] = [column for column in FEATURES if frame[column].isna().all()]
    summary = {"generated_at": utc_now(), "is_mock": False, "history": describe(history),
               "calendar_2025": describe(year), "calendar_2025_split": split_report,
               "split_definition": "Mirrors Role B's documented 55/20/25 unique-hour chronological split with strict 72-hour embargoes; no model fitted or ML training dependencies required.",
               "is_model_evaluation": False}
    write_json(bundle / "training_data_summary.json", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data/demo/role_a_real")
    parser.add_argument("--stage", choices=["select", "weather", "assemble", "validate", "all"], default="all")
    parser.add_argument("--cache-only", action="store_true")
    args = parser.parse_args()
    selection = select_cells(args.output_dir)
    if args.stage in {"weather", "all"}:
        fetch_selected_weather(args.output_dir, selection, args.cache_only)
    if args.stage in {"assemble", "all"}:
        print(json.dumps(assemble_selected(args.output_dir, selection)), flush=True)
    if args.stage in {"validate", "all"}:
        audit_selection(args.output_dir, selection)


if __name__ == "__main__":
    main()
