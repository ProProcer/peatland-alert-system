"""Role C entry point: mock replay or live deterministic policy."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from contracts.validate import ROOT, validate_file, validate_payload

from c_agent import llm
from c_agent.policy import decide, dispatch_timestamp
from c_agent.state_store import StateStore, format_ts
from c_agent.water import DEFAULT_MAX_WATER_KM, load_water_catalogue, resolve_water_catalogue_path

PACKAGE = Path(__file__).resolve().parent


def _atomic_write(path: Path, payload: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _append_log(log_path: Path, records: list[dict]) -> None:
    if not records:
        return
    log_path.parent.mkdir(parents=True, exist_ok=True)
    stamp = format_ts(datetime.now(timezone.utc))
    with log_path.open("a", encoding="utf-8") as handle:
        for row in records:
            audiences = ",".join(row["audiences"])
            handle.write(
                f"{stamp} SIMULATED action={row['action']} dispatch_id={row['dispatch_id']} "
                f"cell_id={row['cell_id']} priority={row['priority']} audiences={audiences}\n"
            )


def _require_inputs(data_dir: Path, names: tuple[str, ...]) -> None:
    missing = [name for name in names if not (data_dir / name).exists()]
    if missing:
        raise SystemExit(
            f"C: missing input file(s) in {data_dir}: {', '.join(missing)}. "
            "Run the upstream stage first (A writes features.json/cells.geojson, B writes risk.json); "
            "C does not substitute mocks for live inputs."
        )


def dispatch_mock(data_dir: Path, output: Path) -> None:
    _require_inputs(data_dir, ("features.json", "risk.json", "cells.geojson"))
    features = validate_file("features", data_dir / "features.json")
    validate_file("risk", data_dir / "risk.json")
    validate_file("cells", data_dir / "cells.geojson")
    payload = validate_file("dispatch", PACKAGE / "mock_output.json")
    if not {row["cell_id"] for row in payload} <= {row["cell_id"] for row in features}:
        raise ValueError("The fixed dispatch mock refers to cells missing from the supplied features")
    _atomic_write(output, payload)
    print(f"C: replayed simulated dispatch fixture to {output}")


def dispatch_live(
    data_dir: Path,
    output: Path,
    *,
    state_path: Path | None = None,
    log_path: Path | None = None,
    water_sources: Path | None = None,
    cooldown_hours: float = 6.0,
    now: datetime | None = None,
    use_llm: bool = False,
    max_water_km: float | None = DEFAULT_MAX_WATER_KM,
) -> list:
    _require_inputs(data_dir, ("features.json", "risk.json", "cells.geojson"))
    features = validate_file("features", data_dir / "features.json")
    risk_rows = validate_file("risk", data_dir / "risk.json")
    validate_file("cells", data_dir / "cells.geojson")

    catalogue_path = resolve_water_catalogue_path(water_sources, data_dir)
    water_candidates = load_water_catalogue(catalogue_path)
    if catalogue_path is None:
        print("C: no water catalogue found; water_source will be null")
    else:
        print(f"C: loaded {len(water_candidates)} water candidate(s) from {catalogue_path}")

    store = StateStore(state_path or PACKAGE / "state" / "incidents.json", cooldown_hours=cooldown_hours)
    if now is None and risk_rows:
        latest_risk_ts = max(row["ts"] for row in risk_rows)
        now = dispatch_timestamp(latest_risk_ts)

    rewriter = None
    if use_llm:
        rewriter = llm.make_rewriter()
        if rewriter is None:
            print("C: --llm requested but no GEMINI_API_KEY (or ANTHROPIC_API_KEY) is set; using templates")

    payload, created = decide(
        features,
        risk_rows,
        store,
        now=now,
        water_candidates=water_candidates,
        max_water_km=max_water_km,
        rewriter=rewriter,
    )
    validate_payload("dispatch", payload)
    store.save()
    _atomic_write(output, payload)
    _append_log(log_path or PACKAGE / "logs" / "notifications.log", created)
    print(f"C: wrote {len(payload)} simulated dispatch record(s) to {output} ({len(created)} new)")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mock", action="store_true", help="Replay the fixed mock_output.json fixture")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data/demo")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--state-path", type=Path, default=None)
    parser.add_argument("--log-path", type=Path, default=None)
    parser.add_argument(
        "--water-sources",
        type=Path,
        default=None,
        help="Role A water catalogue JSON (default: data-dir/water_sources.json or a_data/mock_water_sources.json)",
    )
    parser.add_argument("--cooldown-hours", type=float, default=6.0)
    parser.add_argument(
        "--max-water-km",
        type=float,
        default=DEFAULT_MAX_WATER_KM,
        help="Attach a water source only if the nearest is within this distance (default 15); 0 disables the cutoff",
    )
    parser.add_argument(
        "--llm",
        action="store_true",
        help="Let an LLM rephrase messages (needs GEMINI_API_KEY or ANTHROPIC_API_KEY); output is validated, templates are the fallback",
    )
    args = parser.parse_args()
    output = args.output or args.data_dir / "dispatch.json"
    if args.mock:
        dispatch_mock(args.data_dir, output)
        return
    dispatch_live(
        args.data_dir,
        output,
        state_path=args.state_path,
        log_path=args.log_path,
        water_sources=args.water_sources,
        cooldown_hours=args.cooldown_hours,
        use_llm=args.llm,
        max_water_km=args.max_water_km or None,
    )


if __name__ == "__main__":
    main()
