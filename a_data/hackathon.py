"""Prepare today's Central Kalimantan handoff entirely from cached real inputs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from a_data.assemble import assemble
from a_data.common import ROOT, utc_now, write_json, write_parquet


def prepare(output_dir: Path) -> dict:
    cells = pd.read_parquet(output_dir / "cells.parquet")
    cells = cells[cells["province"] == "Central Kalimantan"]
    frames, selected = [], []
    for row in cells.to_dict("records"):
        path = output_dir / "cache/normalized_weather" / f"{row['cell_id']}.parquet"
        if path.exists():
            frames.append(pd.read_parquet(path))
            selected.append(row["cell_id"])
    if not frames:
        raise FileNotFoundError("No normalized Central Kalimantan weather caches are available")
    weather_path = output_dir / "weather_hackathon.parquet"
    write_parquet(pd.concat(frames, ignore_index=True), weather_path)
    report = assemble(output_dir, weather_path, ROOT / "a_data/processing_config.json", "hackathon")
    # A smaller calendar-year dataset lets B start with a quick baseline.
    history = pd.read_parquet(output_dir / "hackathon/history.parquet")
    history_2025 = history[(history["ts"] >= "2025-01-01T00:00:00Z") & (history["ts"] < "2026-01-01T00:00:00Z")]
    write_parquet(history_2025, output_dir / "hackathon/history_2025.parquet")
    scope = {"updated_at": utc_now(), "status": "prepared_for_today_only_deadline",
             "scope": "Cached Central Kalimantan subset", "cell_count": len(selected), "cell_ids": selected,
             "history_rows": report["history_rows"], "history_2025_rows": len(history_2025),
             "first_hour": report["first_hour"], "last_hour": report["last_hour"],
             "snapshot": report["snapshot"], "schema_version": "1.0",
             "model_features": 27, "horizons_h": [24, 48, 72],
             "additional_weather_requests": 0,
             "next": ["B loads history_2025.parquet for a first baseline, or history.parquet for the complete cached period.",
                      "C uses the real water catalogue and matching target lookups.",
                      "E/D integrate a coherent, explicitly dated replay bundle."]}
    write_json(output_dir / "hackathon/scope.json", scope)
    progress_path = output_dir / "weather_history_progress.json"
    if progress_path.exists():
        progress = json.loads(progress_path.read_text())
        progress.update(updated_at=utc_now(), status="stopped_for_today_only_hackathon_scope",
                        note="Completed cell caches retained; regional expansion deferred to focus on the working demo.")
        write_json(progress_path, progress)
    print(json.dumps({k: scope[k] for k in ("scope", "cell_count", "history_rows", "history_2025_rows", "additional_weather_requests")}), flush=True)
    return scope


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data/demo/role_a_real")
    args = parser.parse_args()
    prepare(args.output_dir)


if __name__ == "__main__":
    main()
