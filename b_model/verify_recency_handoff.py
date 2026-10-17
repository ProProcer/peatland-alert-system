"""Independently re-score the frozen recency candidate without fitting/promoting.

Checks all 60 saved comparisons against their daily aggregates, then reproduces
selected-model calibration thresholds and later evaluation from real history.
The full-history control is checked against saved evidence, not refitted here.
"""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

import joblib
import numpy as np
from omegaconf import OmegaConf
import pandas as pd

from b_model.alert_policy import policy_metrics, select_policy_threshold
from b_model.backtest import budget_metrics, validate_protocol
from b_model.config import HORIZONS, PROJECT_ROOT
from b_model.experiment import load_history, probability_metrics, write_json
from b_model.predict import validate_risk_contract
from b_model.recency_study import recency_parts, select_strategies


def fingerprint(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compare(actual, expected, context):
    """Require the same structure/counts; tolerate only numerical roundoff."""
    if isinstance(expected, dict):
        if actual.keys() != expected.keys():
            raise ValueError(f"Different metric fields: {context}")
        for key in expected:
            compare(actual[key], expected[key], f"{context}.{key}")
    elif isinstance(expected, list):
        if len(actual) != len(expected):
            raise ValueError(f"Different metric lengths: {context}")
        for index, (left, right) in enumerate(zip(actual, expected)):
            compare(left, right, f"{context}[{index}]")
    elif isinstance(expected, float):
        if not np.isclose(actual, expected, rtol=1e-9, atol=1e-12):
            raise ValueError(f"Different metric value: {context}: {actual} != {expected}")
    elif actual != expected:
        raise ValueError(f"Different value: {context}: {actual} != {expected}")


def verify(output):
    output = output.resolve()
    if not output.is_relative_to((PROJECT_ROOT / "b_model").resolve()):
        raise ValueError("Verification output must stay inside Role B")
    if output.exists():
        raise FileExistsError("Use a fresh verification directory")
    evidence = PROJECT_ROOT / "b_model/experiment_results/20261017_recency"
    candidate = PROJECT_ROOT / "b_model/model_recency_candidate"
    read = lambda path: json.loads(path.read_text(encoding="utf-8"))
    plan = OmegaConf.to_container(OmegaConf.load(evidence / "protocol.yaml"), resolve=True)
    reference = OmegaConf.to_container(OmegaConf.load(PROJECT_ROOT / plan["reference_windows"]), resolve=True)
    validate_protocol(reference)
    windows = reference["windows"]
    rows, metadata = read(evidence / "results.json"), read(evidence / "metadata.json")
    selection = read(evidence / "selection.json")
    provenance = read(candidate / "provenance.json")
    operating = read(candidate / "operating_points.json")
    protected = [PROJECT_ROOT / "b_model/CURRENT_HANDOFF.json"]
    protected += [p for folder in (PROJECT_ROOT / "b_model/model_regional_40", PROJECT_ROOT / "data/processed")
                  for p in folder.iterdir() if p.is_file()]
    before = {str(p.relative_to(PROJECT_ROOT)): fingerprint(p) for p in protected}
    source = PROJECT_ROOT / plan["history"]
    if fingerprint(source) != metadata["source_sha256"] or metadata["source_sha256"] != provenance["source_sha256"]:
        raise ValueError("History does not match the frozen study/candidate")
    for name, sha in provenance["artifact_sha256"].items():
        if fingerprint(candidate / name) != sha:
            raise ValueError(f"Candidate artifact fingerprint changed: {name}")
    expected_keys = {(w["name"], s["name"], h) for w in windows for s in plan["strategies"] for h in HORIZONS}
    keys = [(r["window"], r["strategy"], r["horizon_h"]) for r in rows]
    if len(keys) != len(expected_keys) or set(keys) != expected_keys or metadata["completed_models"] != len(keys):
        raise ValueError("Missing, duplicate or unexpected saved model comparisons")
    daily = pd.read_csv(evidence / "daily_budget.csv")
    for row in rows:
        for pool in ("all", "quiet"):
            group = daily[(daily.window == row["window"]) & (daily.strategy == row["strategy"])
                          & (daily.horizon_h == row["horizon_h"]) & (daily.pool == pool)]
            metric = row["budgets"][f"daily_00z_{pool}"]
            if group.empty or group.ts.duplicated().any():
                raise ValueError("Missing or duplicated daily budget evidence")
            for key, value in {"snapshots": len(group), "alerts": int(group.alerts.sum()),
                               "hits": int(group.hits.sum()), "positives": int(group.positives.sum()),
                               "false_alerts": int((group.alerts - group.hits).sum())}.items():
                compare(value, metric[key], f"daily_aggregate.{key}")
            np.testing.assert_array_equal(group.alerts, np.minimum(group.eligible_cells, plan["budget"]))
    development = [r for r in rows if r["window"] != windows[-1]["name"]]
    chosen, leaderboard = select_strategies(development, [w["name"] for w in windows[:-1]],
                                           plan["selection"]["minimum_overall_ap_fraction_of_full"])
    compare(chosen, selection["selected"], "development_selection")
    compare(leaderboard, selection["leaderboard"], "development_leaderboard")
    if selection["frozen_before"] != windows[-1]["name"]:
        raise ValueError("Unexpected selection/evaluation boundary")
    history, dropped = load_history(source)
    if len(history) != metadata["complete_rows"] or dropped != metadata["incomplete_labels_excluded"]:
        raise ValueError("Historical label completeness differs from the study")
    selected_results = {}
    for horizon in HORIZONS:
        strategy = chosen[str(horizon)]["strategy"]
        spec = next(s for s in plan["strategies"] if s["name"] == strategy)
        parts = recency_parts(history, windows[-1], spec)
        order = ("train", "probability_calibration", "policy_calibration", "validation")
        for earlier, later in zip(order, order[1:]):
            if parts[earlier]._time.max() + pd.Timedelta(hours=72) >= parts[later]._time.min():
                raise ValueError("Insufficient temporal purge")
        bag = joblib.load(candidate / f"model_{horizon}h.joblib")
        model, columns = bag["primary_model"], bag["feature_columns"]
        recorded = next(r for r in rows if r["window"] == windows[-1]["name"]
                        and r["strategy"] == strategy and r["horizon_h"] == horizon)
        scores = {name: model.predict_proba(bag["imputer"].transform(parts[name][columns]))[:, 1]
                  for name in ("policy_calibration", "validation")}
        val = parts["validation"]
        labels = val[f"target_{horizon}h"].to_numpy(dtype=int)
        quiet = val.hotspots_in_cell_24h.eq(0).fillna(False).to_numpy(dtype=bool)
        compare(probability_metrics(labels, scores["validation"]), recorded["metrics"], f"{horizon}.overall")
        compare(probability_metrics(labels[quiet], scores["validation"][quiet]), recorded["quiet_metrics"], f"{horizon}.quiet")
        for pool in ("all", "quiet"):
            cal = parts["policy_calibration"]
            cmask = cal._time.dt.hour.eq(0).to_numpy()
            if pool == "quiet":
                cmask &= cal.hotspots_in_cell_24h.eq(0).fillna(False).to_numpy(dtype=bool)
            policy = select_policy_threshold(cal.loc[cmask], scores["policy_calibration"][cmask],
                cal[f"target_{horizon}h"].to_numpy(dtype=int)[cmask], plan["budget"])
            frozen = operating["horizons"][str(horizon)]["policies"][pool]
            compare(policy, frozen, f"{horizon}.{pool}.calibration_policy")
            mask = val._time.dt.hour.eq(0).to_numpy()
            if pool == "quiet":
                mask &= quiet
            metrics, _ = budget_metrics(val.loc[mask], scores["validation"][mask], labels[mask], plan["budget"])
            compare(metrics, recorded["budgets"][f"daily_00z_{pool}"], f"{horizon}.{pool}.budget")
            result = policy_metrics(val.loc[mask], scores["validation"][mask], labels[mask], plan["budget"], policy["threshold"])
            compare(result, recorded["policies"][pool]["validation"], f"{horizon}.{pool}.later_policy")
        control = next(r for r in rows if r["window"] == windows[-1]["name"] and r["strategy"] == "full"
                       and r["horizon_h"] == horizon)
        selected_results[str(horizon)] = {"strategy": strategy,
            "full_history_quiet_budget": control["budgets"]["daily_00z_quiet"],
            "selected_quiet_budget": recorded["budgets"]["daily_00z_quiet"],
            "selected_quiet_policy": recorded["policies"]["quiet"]}
    audit = read(PROJECT_ROOT / "b_model/experiment_results/20261017_source_consistency/audit.json")
    for row in audit["files"]:
        if fingerprint(PROJECT_ROOT / row["path"]) != row["sha256"]:
            raise ValueError("Raw FIRMS source fingerprint differs from the audit")
    output.mkdir(parents=True)
    start = time.perf_counter()
    command = [sys.executable, "-m", "b_model.predict", "--config-name", "replay_recency",
               f"paths.output={(output / 'risk.json').as_posix()}"]
    completed = subprocess.run(command, cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=60)
    if completed.returncode:
        raise RuntimeError(f"Candidate inference failed: {completed.stderr[-2000:]}")
    elapsed = time.perf_counter() - start
    risk = read(output / "risk.json")
    validate_risk_contract(risk)
    if len(risk) != 120 or {r["cell_id"] for r in risk} != set(provenance["scope_cell_ids"]):
        raise ValueError("Candidate replay has the wrong cell/horizon coverage")
    compare(risk, read(evidence / "risk.json"), "saved_candidate_replay")
    after = {str(p.relative_to(PROJECT_ROOT)): fingerprint(p) for p in protected}
    compare(after, before, "protected_handoff_and_shared_feeds")
    report = {"status": "verified", "saved_comparisons": len(rows),
              "daily_budget_groups_checked": len(rows) * 2,
              "selected_candidate_models_rescored": len(HORIZONS),
              "verification_scope": "Saved evidence consistency, development-only selection, independently reproduced selected-model policies/final scores and fresh CLI replay. No refitting or promotion.",
              "full_history_control": "Daily aggregates verified; control models were not refitted or independently rescored because original ignored run artifacts are not part of this handoff.",
              "results": selected_results, "fresh_cli_seconds": elapsed, "replay_records": len(risk),
              "source_history_sha256": metadata["source_sha256"],
              "source_consistency_status": audit["status"],
              "source_consistency_limitation": "No overlap or original export settings; attribution remains unresolved. All four local raw file fingerprints match the audit.",
              "current_handoff_and_shared_feeds_unchanged": True, "protected_sha256": before}
    write_json(output / "verification.json", report)
    print(json.dumps({k: report[k] for k in ("status", "saved_comparisons", "selected_candidate_models_rescored", "replay_records", "fresh_cli_seconds", "source_consistency_status")}, indent=2))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "b_model/runs/recency_handoff_verification")
    verify(parser.parse_args().output_dir)
