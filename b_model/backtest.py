"""Retrospective paired walk-forward evaluation and fixed-budget ranking.

No deployment, hyperparameter search, threshold selection or shared feed writes.
"""
from __future__ import annotations

import argparse
import hashlib
from importlib.metadata import version
from pathlib import Path
import time

import joblib
import numpy as np
from omegaconf import OmegaConf
import pandas as pd
from sklearn.impute import SimpleImputer
from xgboost import XGBClassifier, __version__ as xgboost_version

from b_model.config import FEATURE_COLUMNS, HORIZONS, PROJECT_ROOT
from b_model.experiment import (calibrate, fit_model, load_history,
    partition_summary, prepare, probability_metrics, select_candidates, split_window, utc, write_json)
from b_model.leading_indicators import (ENGINEERED_FEATURES, ENSEMBLE_FEATURES,
    add_leading_indicators, cold_start_sample_weights)


def budget_metrics(frame: pd.DataFrame, scores, labels, budget: int) -> tuple[dict, pd.DataFrame]:
    """Select up to k eligible cells per timestamp, with stable label-blind ties.

    Micro precision/recall count cell/windows, not distinct fires. Random expected
    hits condition on the exact eligible pool and positive count at each time.
    """
    if isinstance(budget, bool) or not isinstance(budget, int) or budget < 1:
        raise ValueError("Budget must be a positive integer")
    p, y = np.asarray(scores, dtype=float), np.asarray(labels)
    if p.shape != (len(frame),) or y.shape != p.shape:
        raise ValueError("Scores and labels must align with eligible rows")
    if not np.isfinite(p).all() or ((p < 0) | (p > 1)).any() or not np.isin(y, [0, 1]).all():
        raise ValueError("Expected finite probabilities and binary labels")
    if frame[["ts", "cell_id"]].isna().any().any() or frame.duplicated(["ts", "cell_id"]).any():
        raise ValueError("Eligible cells must have unique nonmissing timestamp/cell keys")
    rows = frame[["ts", "cell_id"]].copy()
    rows["score"], rows["label"] = p, y.astype(int)
    rows = rows.sort_values(["ts", "score", "cell_id"], ascending=[True, False, True])
    rank = rows.groupby('ts', sort=True).cumcount()
    rows['_selected'] = rank < budget
    rows['_hit'] = rows.label.where(rows['_selected'], 0)
    detail = rows.groupby('ts', sort=True).agg(eligible_cells=('cell_id','size'),
        positives=('label','sum'), alerts=('_selected','sum'), hits=('_hit','sum'))
    detail['random_expected_hits'] = detail.alerts * detail.positives / detail.eligible_cells
    kth = rows.loc[rank.eq(budget-1)].set_index('ts').score
    following = rows.loc[rank.eq(budget)].set_index('ts').score
    detail['boundary_tie'] = kth.eq(following).reindex(detail.index, fill_value=False)
    detail = detail.reset_index()
    hits, alerts, positives = [int(detail[c].sum()) for c in ("hits", "alerts", "positives")]
    expected = float(detail.random_expected_hits.sum())
    result = {"snapshots": len(detail), "eligible_rows": len(rows), "budget": budget,
        "alerts": alerts, "hits": hits, "false_alerts": alerts - hits,
        "positives": positives, "missed_positive_windows": positives - hits,
        "precision": hits / alerts if alerts else None,
        "recall": hits / positives if positives else None,
        "random_expected_hits": expected, "lift_over_random": hits / expected if expected else None,
        "snapshots_with_positives": int((detail.positives > 0).sum()),
        "positive_snapshots_with_a_hit": int(((detail.positives > 0) & (detail.hits > 0)).sum()),
        "snapshots_below_budget": int((detail.eligible_cells < budget).sum()),
        "boundary_tie_snapshots": int(detail.boundary_tie.sum())}
    return result, detail


def validate_protocol(plan: dict) -> None:
    if not isinstance(plan["budget"], int) or plan["budget"] < 1 or plan["embargo_hours"] < max(HORIZONS):
        raise ValueError("Positive budget and at least 72-hour embargo required")
    names = [w["name"] for w in plan["windows"]]
    if not names or len(set(names)) != len(names):
        raise ValueError("Nonempty uniquely named windows required")
    previous_end = None
    for w in plan["windows"]:
        end, cs, ce, vs, ve = [utc(w[k]) for k in ("train_end", "calibration_start",
            "calibration_end", "validation_start", "validation_end")]
        gap = pd.Timedelta(hours=plan["embargo_hours"])
        if not end <= cs < ce <= vs < ve or cs - end < gap or vs - ce < gap:
            raise ValueError("Invalid chronological boundaries or embargo")
        if previous_end is not None and vs < previous_end:
            raise ValueError("Evaluation windows must not overlap")
        previous_end = ve


def run(plan: dict) -> None:
    validate_protocol(plan)
    output, evidence = [PROJECT_ROOT / plan[k] for k in ("output_dir", "evidence_dir")]
    if output.exists() or evidence.exists():
        raise FileExistsError("Use fresh output and evidence directories; do not overwrite an evaluation")
    source = PROJECT_ROOT / plan["history"]
    source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    output.mkdir(parents=True)
    evidence.mkdir(parents=True)
    for directory in (output, evidence):
        OmegaConf.save(OmegaConf.create(plan), directory / "protocol.yaml")
    # Compute indicators from all predictor hours, then join validated complete labels.
    indicators = add_leading_indicators(pd.read_parquet(source))[["cell_id", "ts", *ENGINEERED_FEATURES]]
    history, incomplete = load_history(source)
    history = history.merge(indicators, on=["cell_id", "ts"], how="left", validate="one_to_one")
    metadata = {"source_sha256": source_sha, "complete_rows": len(history), "incomplete_rows_excluded": incomplete,
        "status": "Retrospective: periods and LR settings previously inspected. No tuning or promotion.",
        "libraries": {**{name: version(name) for name in ("numpy", "pandas", "scikit-learn")}, "xgboost": xgboost_version},
        "ranking": "Top 5 independently per horizon; no probability cutoff; cell_id ascending breaks ties.",
        "snapshot_policy": "Primary: daily 00:00 UTC; secondary: every available hour. Not distinct events or dispatches.",
        "quiet_policy": "Separate budget among cells with observed hotspots_in_cell_24h == 0; unknowns excluded.",
        "fit_policy": "Retrain each model before each evaluation; fit preprocessing on train and sigmoid on calibration only."}
    write_json(evidence / "metadata.json", metadata)
    results, daily = [], []
    start = time.perf_counter()
    for window in plan["windows"]:
        if window['name'] == plan.get('select_before_window'):
            selection_rows = [{'key': r['backend'], 'horizon_h': r['horizon_h'], 'fold': r['window'],
                'spec': {'backend': r['backend']}, 'calibration': 'sigmoid', 'validation': r['metrics']}
                for r in results]
            selected, leaderboard = select_candidates(selection_rows,
                list(dict.fromkeys(r['window'] for r in results)))
            write_json(evidence / 'selection.json', {'selected': selected, 'leaderboard': leaderboard,
                'frozen_before': window['name'], 'rule': 'Mean development AP, then mean Brier; baseline is reference only.'})
        parts = split_window(history, window)
        write_json(evidence / f"split_{window['name']}.json", partition_summary(parts))
        val = parts["validation"]
        backends = ['logistic_regression', 'xgboost']
        if plan.get('include_dryness_baseline', False):
            backends.append('dryness_baseline')
        for backend in backends:
            columns = ENSEMBLE_FEATURES if backend == 'xgboost' else FEATURE_COLUMNS
            if parts["train"][columns].isna().all().any():
                raise ValueError("Cannot fit a training median to an entirely missing predictor")
            imputer = SimpleImputer(strategy="median").fit(parts["train"][columns])
            matrices = {key: imputer.transform(part[columns]) for key, part in parts.items()}
            if backend == 'dryness_baseline':
                _, _, arrays = prepare(parts)
                matrices = arrays['baseline']
            for h in HORIZONS:
                begin = time.perf_counter()
                ys = {key: part[f"target_{h}h"].to_numpy(dtype=int) for key, part in parts.items()}
                weighting = None
                if backend in ('logistic_regression', 'dryness_baseline'):
                    model = fit_model({"backend": backend, "c": plan["logistic_c"][str(h)] if backend == 'logistic_regression' else 1.0},
                        plan["seed"], matrices["train"], ys["train"])
                else:
                    settings = dict(plan["xgboost"])
                    multiplier = settings.pop("cold_start_multiplier")
                    weights, weighting = cold_start_sample_weights(parts["train"], ys["train"], multiplier)
                    model = XGBClassifier(**settings, objective="binary:logistic", eval_metric="aucpr",
                        tree_method="hist", random_state=plan["seed"], n_jobs=2, scale_pos_weight=1.0)
                    model.fit(matrices["train"], ys["train"], sample_weight=weights)
                fitted = calibrate(model, matrices["calibration"], ys["calibration"], h, "sigmoid")
                scores = fitted.predict_proba(matrices["validation"])[:, 1]
                stem = f"{window['name']}_{backend}_{h}h"
                joblib.dump({"model": fitted, "imputer": imputer, "feature_columns": columns}, output / f"{stem}.joblib")
                predictions = val[["cell_id", "ts", "hotspots_in_cell_24h"]].copy()
                predictions["label"], predictions["score"] = ys["validation"], scores
                predictions.to_parquet(output / f"{stem}_predictions.parquet", index=False)
                quiet = val.hotspots_in_cell_24h.eq(0).fillna(False).to_numpy(dtype=bool)
                result = {"window": window["name"], "backend": backend, "horizon_h": h,
                    "sample_weighting": weighting, "metrics": probability_metrics(ys["validation"], scores),
                    "quiet_metrics": probability_metrics(ys["validation"][quiet], scores[quiet]) if quiet.any() else None,
                    "budgets": {}}
                for cadence, cadence_mask in (("daily_00z", val._time.dt.hour.eq(0).to_numpy()),
                                              ("hourly", np.ones(len(val), dtype=bool))):
                    for pool, pool_mask in (("all", np.ones(len(val), dtype=bool)), ("quiet", quiet)):
                        mask = cadence_mask & pool_mask
                        metric, detail = budget_metrics(val.loc[mask], scores[mask], ys["validation"][mask], plan["budget"])
                        key = f"{cadence}_{pool}"
                        result["budgets"][key] = metric
                        if cadence == "daily_00z":
                            detail = detail.assign(window=window["name"], backend=backend, horizon_h=h, pool=pool)
                            daily.append(detail)
                result["fit_and_score_seconds"] = time.perf_counter() - begin
                results.append(result)
                write_json(evidence / "results.json", results)
                print(f"{stem}: AP={result['metrics']['pr_auc']:.4f}, quiet AP={result['quiet_metrics']['pr_auc']}, "
                    f"daily top5 hits={result['budgets']['daily_00z_all']['hits']}", flush=True)
    pd.concat(daily, ignore_index=True).to_csv(evidence / "daily_budget.csv", index=False)
    pd.DataFrame([{'window':r['window'], 'backend':r['backend'], 'horizon_h':r['horizon_h'],
        'cadence_pool':key, **metric} for r in results for key,metric in r['budgets'].items()]
        ).to_csv(evidence / 'budget_summary.csv', index=False)
    metadata["runtime_seconds"] = time.perf_counter() - start
    metadata["completed_models"] = len(results)
    assert hashlib.sha256(source.read_bytes()).hexdigest() == source_sha
    write_json(evidence / "metadata.json", metadata)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=PROJECT_ROOT / "b_model/conf/backtest.yaml")
    args = parser.parse_args()
    run(OmegaConf.to_container(OmegaConf.load(args.config), resolve=True))
