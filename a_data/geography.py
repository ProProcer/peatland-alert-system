"""Build all Indonesian Kalimantan peat cells using versioned boundaries."""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path

import pandas as pd
import requests
import shapely
from pyproj import Transformer
from shapely.geometry import GeometryCollection, box, mapping, shape
from shapely.ops import transform
from shapely.strtree import STRtree

from a_data.common import ROOT, sha256, utc_now, write_json, write_parquet

BOUNDARY_API = "https://www.geoboundaries.org/api/current/gbOpen/IDN/ADM1/"
AREA_CRS = "+proj=laea +lat_0=0 +lon_0=114 +datum=WGS84 +units=m +no_defs"
TO_AREA = Transformer.from_crs("EPSG:4326", AREA_CRS, always_xy=True).transform


def polygonal(geometry):
    geometry = shapely.make_valid(shapely.force_2d(geometry))
    if geometry.geom_type in {"Polygon", "MultiPolygon"}:
        return geometry
    if hasattr(geometry, "geoms"):
        parts = [polygonal(part) for part in geometry.geoms]
        return shapely.union_all([part for part in parts if not part.is_empty])
    return GeometryCollection()


def load_boundary(cache_dir: Path, download: bool = False):
    metadata_path = cache_dir / "boundary_metadata.json"
    source_path = cache_dir / "geoBoundaries-IDN-ADM1.geojson"
    if not metadata_path.exists() or not source_path.exists():
        if not download:
            raise FileNotFoundError("Boundary cache is missing; run geography with --download-boundary.")
        response = requests.get(BOUNDARY_API, timeout=45)
        response.raise_for_status()
        metadata = response.json()
        response = requests.get(metadata["gjDownloadURL"], timeout=120)
        response.raise_for_status()
        payload = response.json()
        if payload.get("type") != "FeatureCollection":
            raise ValueError("Boundary response is not a GeoJSON FeatureCollection")
        metadata.update(retrieved_at=utc_now(), metadata_url=BOUNDARY_API)
        write_json(source_path, payload)
        metadata["downloaded_geojson_sha256"] = sha256(source_path)
        write_json(metadata_path, metadata)
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if sha256(source_path) != metadata["downloaded_geojson_sha256"]:
        raise ValueError("Boundary cache hash differs from recorded provenance")
    source = json.loads(source_path.read_text(encoding="utf-8"))
    provinces = [f for f in source["features"] if "kalimantan" in f["properties"]["shapeName"].lower()]
    if len(provinces) != 5:
        names = [f["properties"]["shapeName"] for f in source["features"]]
        raise ValueError(f"Expected five Kalimantan provinces, found {len(provinces)}; names: {names}")
    for feature in provinces:
        feature["geometry"] = mapping(polygonal(shape(feature["geometry"])))
    regional_cache = cache_dir / "kalimantan_boundary.geojson"
    if not regional_cache.exists():
        write_json(regional_cache, {"type": "FeatureCollection", "features": provinces})
    region = shapely.union_all([shape(f["geometry"]) for f in provinces])
    return region, provinces, metadata


def build_grid(peat_path: Path, output_dir: Path, download: bool = False) -> dict:
    region, provinces, metadata = load_boundary(output_dir / "cache", download)
    source = json.loads(peat_path.read_text(encoding="utf-8-sig"))
    peat_geometries, polygon_ids = [], []
    repaired = 0
    for feature in source["features"]:
        original = shape(feature["geometry"])
        if not original.envelope.intersects(region.envelope):
            continue
        repaired += int(not original.is_valid)
        geometry = polygonal(original)
        if geometry.is_empty or not geometry.intersects(region):
            continue
        clipped = polygonal(geometry.intersection(region))
        if not clipped.is_empty:
            identifier = feature["properties"].get("globalid")
            if not identifier:
                raise ValueError("A retained peat polygon has no globalid")
            peat_geometries.append(clipped)
            polygon_ids.append(str(identifier))
    if not peat_geometries:
        raise ValueError("No peat intersects Indonesian Kalimantan")
    tree = STRtree(peat_geometries)
    projected = [transform(TO_AREA, geometry) for geometry in peat_geometries]
    province_metric = [(f["properties"]["shapeName"], transform(TO_AREA, shape(f["geometry"]))) for f in provinces]
    west, south, east, north = shapely.union_all([g.envelope for g in peat_geometries]).bounds
    features, rows = [], []
    for iy in range(math.floor(south * 10), math.ceil(north * 10)):
        for ix in range(math.floor(west * 10), math.ceil(east * 10)):
            cell = box(ix / 10, iy / 10, (ix + 1) / 10, (iy + 1) / 10)
            indices = tree.query(cell, predicate="intersects")
            if not len(indices):
                continue
            metric_cell = transform(TO_AREA, cell)
            overlaps = [(int(index), projected[index].intersection(metric_cell)) for index in indices]
            overlaps = [(index, geometry) for index, geometry in overlaps if geometry.area > 0]
            peat_area = shapely.union_all([geometry for _, geometry in overlaps]).area
            fraction = peat_area / metric_cell.area
            if fraction < 0.05:
                continue
            if fraction > 1 + 1e-9:
                raise ValueError("Peat overlap exceeds cell area")
            lat, lon = round((iy + 0.5) / 10, 2), round((ix + 0.5) / 10, 2)
            province = max(province_metric, key=lambda item: metric_cell.intersection(item[1]).area)[0]
            properties = {"cell_id": f"{lat:.2f}_{lon:.2f}", "lat": lat, "lon": lon,
                          "peat_fraction": min(fraction, 1.0), "peat_area_km2": peat_area / 1e6,
                          "cell_area_km2": metric_cell.area / 1e6, "province": province,
                          "polygon_ids": sorted({polygon_ids[index] for index, _ in overlaps})}
            rows.append(properties)
            features.append({"type": "Feature", "properties": properties, "geometry": mapping(cell)})
        print(f"Grid: completed latitude strip {iy / 10:.1f}; {len(features)} cells", flush=True)
    if not rows:
        raise ValueError("No cells meet the frozen minimum peat fraction")
    write_json(output_dir / "cells.geojson", {"type": "FeatureCollection", "features": features})
    write_parquet(pd.DataFrame(rows), output_dir / "cells.parquet")
    report = {"generated_at": utc_now(), "is_mock": False, "scope": "All Indonesian Kalimantan",
              "cell_count": len(rows), "cells_by_province": dict(Counter(r["province"] for r in rows)),
              "grid_size_deg": 0.1, "minimum_peat_fraction": 0.05,
              "peat_source_sha256": sha256(peat_path), "retained_peat_features": len(peat_geometries),
              "invalid_source_geometries_repaired": repaired, "area_crs": AREA_CRS,
              "boundary": metadata,
              "boundary_cell_policy": "Peat clipped to Indonesian Kalimantan; full square cell area is the denominator. Province is assigned by largest cell overlap.",
              "weather_budget": {"2025_rows": len(rows) * 8760,
                                 "2025_with_30_day_warmup_estimated_weighted_calls": round(len(rows) * 39.5, 1)}}
    write_json(output_dir / "grid_report.json", report)
    print(json.dumps({k: report[k] for k in ("cell_count", "cells_by_province", "weather_budget")}), flush=True)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--peat", type=Path, default=ROOT / "data/raw/Indonesia_Peat_Lands.geojson")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data/demo/role_a_real")
    parser.add_argument("--download-boundary", action="store_true")
    args = parser.parse_args()
    build_grid(args.peat, args.output_dir, args.download_boundary)


if __name__ == "__main__":
    main()
