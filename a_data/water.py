"""Extract mapped water candidates and query distance from actual incident targets."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import osmium
import shapely
from pyproj import Transformer
from shapely.geometry import Point, mapping, shape
from shapely.ops import nearest_points, transform
from shapely.strtree import STRtree

from a_data.common import ROOT, sha256, utc_now, write_json
from a_data.geography import AREA_CRS, TO_AREA, load_boundary, polygonal


def water_kind(tags) -> str | None:
    if tags.get("waterway") in {"river", "canal", "stream"}:
        return tags["waterway"]
    if tags.get("waterway") == "riverbank":
        return "river"
    if tags.get("natural") == "water" and tags.get("water") not in {"sea", "ocean"}:
        return tags.get("water", "water")
    if tags.get("landuse") in {"reservoir", "basin"}:
        return tags["landuse"]
    if tags.get("emergency") in {"water_tank", "fire_hydrant", "suction_point", "fire_water_pond"}:
        return tags["emergency"]
    if tags.get("man_made") in {"water_well", "water_tap"}:
        return tags["man_made"]
    return None


def extract(pbf_path: Path, output_dir: Path) -> dict:
    region, _, _ = load_boundary(output_dir / "cache")
    shapely.prepare(region)
    factory = osmium.geom.GeoJSONFactory()
    candidates, seen, counts, failures = [], set(), Counter(), []
    processor = osmium.FileProcessor(str(pbf_path)).with_areas().with_filter(
        osmium.filter.KeyFilter("waterway", "natural", "landuse", "emergency", "man_made"))
    for obj in processor:
        if obj.is_relation():
            continue  # Multipolygon relations arrive later as assembled areas.
        kind = water_kind(obj.tags)
        if kind is None:
            continue
        tags = dict(obj.tags)
        if obj.is_area():
            if tags.get("waterway") in {"river", "canal", "stream"} and tags.get("natural") != "water":
                continue  # A closed linear waterway is still a line.
            object_type, object_id = ("way" if obj.from_way() else "relation"), obj.orig_id()
            create = lambda: factory.create_multipolygon(obj)
        elif obj.is_way():
            if obj.is_closed() and (tags.get("natural") == "water" or tags.get("landuse") in {"reservoir", "basin"}
                                   or tags.get("waterway") == "riverbank"):
                continue  # Handled by the assembled area, including any holes.
            object_type, object_id = "way", obj.id
            create = lambda: factory.create_linestring(obj)
        elif obj.is_node():
            object_type, object_id = "node", obj.id
            create = lambda: factory.create_point(obj)
        else:
            continue
        source_id = f"osm:{object_type}/{object_id}"
        if source_id in seen:
            continue
        try:
            geometry = shapely.force_2d(shape(json.loads(create())))
            if geometry.geom_type in {"Polygon", "MultiPolygon"}:
                geometry = polygonal(geometry)
            elif not geometry.is_valid:
                geometry = shapely.make_valid(geometry)
            if geometry.is_empty or not region.intersects(geometry):
                counts["outside_region_or_empty"] += 1
                continue
            if not region.covers(geometry):
                geometry = geometry.intersection(region)
        except (RuntimeError, ValueError, shapely.errors.GEOSException) as exc:
            counts["geometry_failures"] += 1
            failures.append({"source_id": source_id, "error": str(exc)})
            continue
        if geometry.is_empty:
            counts["outside_region_or_empty"] += 1
            continue
        seen.add(source_id)
        props = {"source_id": source_id, "osm_type": object_type, "osm_id": object_id,
                 "kind": kind, "name": tags.get("name"), "is_mock": False,
                 "water_available": None, "access": tags.get("access"),
                 "intermittent": tags.get("intermittent"), "seasonal": tags.get("seasonal"),
                 "tags": tags}
        candidates.append({"type": "Feature", "properties": props, "geometry": mapping(geometry)})
        counts["retained"] += 1
        if len(candidates) % 5000 == 0:
            print(f"Water: {len(candidates):,} candidates", flush=True)
    if not candidates:
        raise ValueError("No mapped water candidates extracted")
    candidates.sort(key=lambda feature: feature["properties"]["source_id"])
    write_json(output_dir / "water_sources.geojson", {"type": "FeatureCollection", "features": candidates}, compact=True)
    report = {"generated_at": utc_now(), "is_mock": False, "source": pbf_path.name,
              "source_sha256": sha256(pbf_path), "attribution": "OpenStreetMap contributors / Geofabrik",
              "license": "ODbL-1.0", "license_url": "https://www.openstreetmap.org/copyright",
              "counts": dict(counts), "geometry_failures": failures,
              "by_kind": dict(Counter(f["properties"]["kind"] for f in candidates)),
              "by_osm_type": dict(Counter(f["properties"]["osm_type"] for f in candidates)),
              "availability": "Mapped candidates only. Presence, suitability and access are not verified.",
              "temporal_use": "2026-10-16 OSM snapshot; supporting dispatch data, excluded from historical model features."}
    write_json(output_dir / "water_report.json", report)
    print(json.dumps({"water_candidates": len(candidates), "by_kind": report["by_kind"]}), flush=True)
    return report


class WaterIndex:
    """Nearest mapped line, point, or polygon shoreline in a local metric projection.

    Does not filter suitability or decide the operational search radius; C owns those rules.
    """

    def __init__(self, path: Path):
        self.features = json.loads(path.read_text(encoding="utf-8"))["features"]
        self.geometry = []
        for feature in self.features:
            geometry = shape(feature["geometry"])
            if geometry.geom_type in {"Polygon", "MultiPolygon"}:
                geometry = geometry.boundary
            self.geometry.append(transform(TO_AREA, geometry))
        self.tree = STRtree(self.geometry)
        self.to_wgs = Transformer.from_crs(AREA_CRS, "EPSG:4326", always_xy=True).transform

    def nearest(self, lat: float, lon: float, max_distance_km: float | None = None) -> dict:
        if not self.geometry:
            return {"source_id": None, "water_source": None}
        target = transform(TO_AREA, Point(lon, lat))
        index = int(self.tree.nearest(target))
        point = nearest_points(target, self.geometry[index])[1]
        distance_km = target.distance(point) / 1000
        if max_distance_km is not None and distance_km > max_distance_km:
            return {"source_id": None, "water_source": None}
        location = transform(self.to_wgs, point)
        properties = self.features[index]["properties"]
        return {"source_id": properties["source_id"], "water_source": {
            "lat": location.y, "lon": location.x, "distance_km": round(distance_km, 3), "kind": properties["kind"]}}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pbf", type=Path, default=ROOT / "data/raw/kalimantan-261016.osm.pbf")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data/demo/role_a_real")
    args = parser.parse_args()
    extract(args.pbf, args.output_dir)


if __name__ == "__main__":
    main()
