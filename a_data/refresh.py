"""Export Role A mock, dated replay, or current live feature bundles."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from contracts.validate import ROOT, validate_file

PACKAGE = Path(__file__).resolve().parent


def refresh_mock(output_dir: Path) -> None:
    sources = [("features", PACKAGE / "mock_output.json", "features.json"),
               ("cells", PACKAGE / "fixtures/cells.geojson", "cells.geojson")]
    payloads = [(name, validate_file(kind, source)) for kind, source, name in sources]
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, payload in payloads:
        target = output_dir / name
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(target)
    print(f"A: wrote synthetic features and cells to {output_dir}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--mock", action="store_true")
    mode.add_argument("--replay", action="store_true", help="Export prepared real historical inputs; not a current-hour feed")
    mode.add_argument("--live", action="store_true", help="Fetch current Open-Meteo and FIRMS data for the frozen 40-cell regional bundle")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--source-dir", type=Path, default=ROOT / "data/demo/role_a_real/hackathon")
    args = parser.parse_args()
    if args.mock:
        refresh_mock(args.output_dir or ROOT / "data/demo")
    elif args.replay:
        refresh_replay(args.source_dir, args.output_dir or ROOT / "data/demo/role_a_replay")
    elif args.live:
        from a_data.live import refresh_live

        source_dir = args.source_dir
        if source_dir == ROOT / "data/demo/role_a_real/hackathon":
            source_dir = ROOT / "data/demo/role_a_real/regional_40"
        refresh_live(source_dir, args.output_dir or ROOT / "data/demo/role_a_real/live")
    else:
        parser.exit(2, "Role A live ingestion is not implemented for current-hour data; fresh FIRMS coverage and platform integration are pending. Use --replay for prepared real historical inputs, or --mock for fixtures.\n")


def refresh_replay(source_dir: Path, output_dir: Path) -> None:
    features = validate_file("features", source_dir / "features.json")
    cells = validate_file("cells", source_dir / "cells.geojson")
    if {row["cell_id"] for row in features} != {cell["properties"]["cell_id"] for cell in cells["features"]}:
        raise ValueError("Replay features and geometry refer to different cells")
    names = ("features.json", "features.parquet", "history.parquet", "cells.geojson")
    for name in names:
        if not (source_dir / name).is_file():
            raise FileNotFoundError(source_dir / name)
    output_dir.mkdir(parents=True, exist_ok=True)
    for name in names:
        target = output_dir / name
        temporary = target.with_suffix(target.suffix + ".tmp")
        shutil.copyfile(source_dir / name, temporary)
        temporary.replace(target)
    print(f"A: exported real historical replay ({features[0]['ts']}, {len(features)} cells) to {output_dir}")


if __name__ == "__main__":
    main()
