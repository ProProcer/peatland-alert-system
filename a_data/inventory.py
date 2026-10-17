"""Inventory actual local source files without inferring observation coverage."""

from __future__ import annotations

import argparse
import csv
import json
import platform
from collections import Counter
from pathlib import Path

from a_data.common import ROOT, sha256, utc_now, write_json


def source_record(path: Path) -> dict:
    record = {"path": path.relative_to(ROOT).as_posix(), "size_bytes": path.stat().st_size,
              "sha256": sha256(path), "source_url": None, "license": None,
              "downloaded_at": None, "declared_coverage": None}
    with path.open("rb") as stream:
        if stream.read(128).startswith(b"version https://git-lfs.github.com/spec/v1"):
            raise ValueError(f"Unhydrated Git LFS pointer: {path}. Run git lfs pull.")
    if path.suffix == ".csv":
        counts, confidence, satellites = Counter(), Counter(), Counter()
        with path.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            record["columns"] = reader.fieldnames
            for row in reader:
                counts[row["acq_date"]] += 1
                confidence[row["confidence"]] += 1
                satellites[row["satellite"]] += 1
        record.update(source="NASA FIRMS", source_url="https://firms.modaps.eosdis.nasa.gov/download/",
                      row_count=sum(counts.values()), detected_date_min=min(counts) if counts else None,
                      detected_date_max=max(counts) if counts else None,
                      detections_by_day=dict(sorted(counts.items())), confidence_counts=dict(confidence),
                      satellite_counts=dict(satellites), coverage_status="unconfirmed_export_manifest_needed")
    elif path.suffix == ".pbf":
        record.update(source="OpenStreetMap / Geofabrik",
                      source_url=f"https://download.geofabrik.de/asia/indonesia/{path.name}",
                      license="ODbL-1.0", attribution="OpenStreetMap contributors",
                      license_url="https://www.openstreetmap.org/copyright")
    elif path.suffix == ".geojson":
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        record.update(source="Indonesian peat layer; exact layer provenance pending",
                      feature_count=len(data["features"]), source_crs=data.get("crs"),
                      geometry_types=dict(Counter(f["geometry"]["type"] for f in data["features"])),
                      properties=sorted(data["features"][0]["properties"]) if data["features"] else [])
    return record


def build_inventory(raw_dir: Path, output_dir: Path) -> dict:
    paths = sorted(p for p in raw_dir.rglob("*") if p.is_file() and p.suffix in {".csv", ".geojson", ".pbf"})
    records = []
    for path in paths:
        print(f"Inventory: {path.name}", flush=True)
        records.append(source_record(path))
    manifest = {"generated_at": utc_now(), "is_mock": False, "scope": "All Indonesian Kalimantan",
                "python": platform.python_version(), "sources": records,
                "notes": ["Detection date ranges do not establish continuous observation coverage.",
                          "Original downloaded files remain unchanged."]}
    config_path = ROOT / "a_data/processing_config.json"
    if config_path.exists():
        config = json.loads(config_path.read_text(encoding="utf-8"))
        manifest["requested_window"] = {key: config[key] for key in ("start_date", "end_date")}
        manifest["firms_declared_export_coverage"] = config["firms_export_coverage"]
        manifest["processing_config_sha256"] = sha256(config_path)
        for record in records:
            if record["path"].endswith(".csv"):
                record["coverage_status"] = "aggregate feed coverage declared by human; see firms_declared_export_coverage"
    write_json(output_dir / "source_manifest.json", manifest)
    print(f"Inventoried {len(records)} sources", flush=True)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=ROOT / "data/raw")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data/demo/role_a_real")
    args = parser.parse_args()
    build_inventory(args.raw_dir, args.output_dir)


if __name__ == "__main__":
    main()
