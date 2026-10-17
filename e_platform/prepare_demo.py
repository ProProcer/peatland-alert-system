"""Replay role mocks into an isolated, validated offline handoff directory."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from a_data.refresh import refresh_mock
from c_agent.agent import dispatch_mock
from contracts.validate import ROOT, validate_directory, validate_file


def prepare_demo(output_dir: Path) -> None:
    output_dir = output_dir.resolve()
    protected = [ROOT / "data/processed", ROOT / "b_model", ROOT / "contracts"]
    if output_dir == ROOT or any(output_dir == path or output_dir.is_relative_to(path) for path in protected):
        raise ValueError("Choose a separate mock output directory, such as data/demo or a temporary folder")
    # Validate every source before writing a handoff.
    validate_file("features", ROOT / "a_data/mock_output.json")
    validate_file("cells", ROOT / "a_data/fixtures/cells.geojson")
    risk = validate_file("risk", ROOT / "b_model/mock_output.json")
    validate_file("dispatch", ROOT / "c_agent/mock_output.json")
    refresh_mock(output_dir)
    temporary = output_dir / "risk.json.tmp"
    temporary.write_text(json.dumps(risk, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output_dir / "risk.json")
    print(f"B: replayed risk mock to {output_dir / 'risk.json'} (no inference)")
    dispatch_mock(output_dir, output_dir / "dispatch.json")
    validate_directory(output_dir)
    print(f"E: all mock handoffs validated in {output_dir}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data/demo")
    args = parser.parse_args()
    try:
        prepare_demo(args.output_dir)
    except (ValueError, OSError) as error:
        parser.exit(1, f"Mock pipeline failed: {error}\n")


if __name__ == "__main__":
    main()
