"""Role C entry point. Mock replay is ready; implement the live policy here."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from contracts.validate import ROOT, validate_file

PACKAGE = Path(__file__).resolve().parent


def dispatch_mock(data_dir: Path, output: Path) -> None:
    features = validate_file("features", data_dir / "features.json")
    validate_file("risk", data_dir / "risk.json")
    validate_file("cells", data_dir / "cells.geojson")
    payload = validate_file("dispatch", PACKAGE / "mock_output.json")
    if not {row["cell_id"] for row in payload} <= {row["cell_id"] for row in features}:
        raise ValueError("The fixed dispatch mock refers to cells missing from the supplied features")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output)
    print(f"C: replayed simulated dispatch fixture to {output}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mock", action="store_true")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data/demo")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not args.mock:
        parser.exit(2, "Role C live policy is not implemented. See c_agent/README.md; use --mock for fixtures.\n")
    dispatch_mock(args.data_dir, args.output or args.data_dir / "dispatch.json")


if __name__ == "__main__":
    main()
