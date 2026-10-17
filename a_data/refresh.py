"""Role A entry point. Mock support is ready; implement live ingestion here."""

from __future__ import annotations

import argparse
import json
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
    parser.add_argument("--mock", action="store_true")
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    if not args.mock:
        parser.exit(2, "Role A live ingestion is not implemented. See a_data/README.md; use --mock for fixtures.\n")
    refresh_mock(args.output_dir or ROOT / "data/demo")


if __name__ == "__main__":
    main()
