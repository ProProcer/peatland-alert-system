"""PIC 2's chronological model comparison, with a separate final evaluation.

Writes only an isolated experiment directory. Published feeds/models are not
replaced. Candidate selection never reads final-period prediction metrics.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import time
import warnings

import joblib
import numpy as np
from omegaconf import OmegaConf
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from b_model.config import FEATURE_COLUMNS, HORIZONS, PROJECT_ROOT, SCHEMA_VERSION
from b_model.train import build_calibrated_model, compute_directional_feature_signs
from b_model.training_config import TrainingConfig, compute_training_dryness


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        temporary.write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def utc(value: str) -> pd.Timestamp:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("Experiment boundaries must be UTC strings ending in Z")
    return pd.Timestamp(value)


def validate_plan(plan: dict) -> None:
    if plan["embargo_hours"] < max(HORIZONS):
        raise ValueError("At least a 72-hour embargo is required")
    if not plan["development"] or not plan["candidates"]:
        raise ValueError("Development windows and candidates must be nonempty")
    if not plan["calibration_methods"] or set(plan["calibration_methods"]) - {"sigmoid", "isotonic"}:
        raise ValueError("Use empirical sigmoid/isotonic calibration only")
    names = [c["name"] for c in plan["candidates"]]
    if len(names) != len(set(names)) or "dryness_baseline" in names:
        raise ValueError("Candidate names must be unique and distinct from the baseline")
    for candidate in plan["candidates"]:
        make_model(candidate, plan["seed"])
    for window in [*plan["development"], plan["final"]]:
        end, cstart, cend, vstart, vend = [utc(window[k]) for k in (
            "train_end", "calibration_start", "calibration_end", "validation_start", "validation_end")]
        gap = pd.Timedelta(hours=plan["embargo_hours"])
        if cstart - end < gap or vstart - cend < gap or not end <= cstart < cend <= vstart < vend:
            raise ValueError(f"Invalid chronological boundaries/embargo in {window['name']}")
    # Candidate selection ends before the final calibration and evaluation periods.
    final_train_end = utc(plan["final"]["train_end"])
    if any(utc(w["validation_end"]) > final_train_end for w in plan["development"]):
        raise ValueError("Development evaluation must end before final calibration/evaluation")


def load_history(path: Path) -> tuple[pd.DataFrame, int]:
    df = pd.read_parquet(path)
    labels = [f"target_{h}h" for h in HORIZONS]
    missing = {"cell_id", "ts", *FEATURE_COLUMNS, *labels} - set(df)
    if missing:
        raise ValueError(f"Missing producer-supplied columns: {sorted(missing)}")
    if df.duplicated(["cell_id", "ts"]).any():
        raise ValueError("Duplicate cell/hour keys")
    if not df.ts.map(lambda s: isinstance(s, str) and s.endswith("Z")).all():
        raise ValueError("History timestamps must end in Z")
    df["_time"] = pd.to_datetime(df.ts, utc=True, errors="raise")
    values = df[FEATURE_COLUMNS].to_numpy(dtype=float)
    if np.isinf(values).any() or (values == -999).any():
        raise ValueError("Nonfinite/sentinel measurements in history")
    observed = df[labels].stack()
    if not observed.isin([0, 1]).all():
        raise ValueError("Labels must be observed 0/1 or explicitly missing")
    complete = df.dropna(subset=labels).sort_values(["ts", "cell_id"]).reset_index(drop=True)
    if complete.empty:
        raise ValueError("No completely labeled rows")
    return complete, len(df) - len(complete)


def split_window(df: pd.DataFrame, window: dict) -> dict[str, pd.DataFrame]:
    t = df["_time"]
    parts = {
        "train": df.loc[t < utc(window["train_end"])],
        "calibration": df.loc[(t >= utc(window["calibration_start"])) & (t < utc(window["calibration_end"]))],
        "validation": df.loc[(t >= utc(window["validation_start"])) & (t < utc(window["validation_end"]))],
    }
    for name, part in parts.items():
        if part.empty:
            raise ValueError(f"Empty {name} partition in {window['name']}")
        for h in HORIZONS:
            if part[f"target_{h}h"].nunique() != 2:
                raise ValueError(f"{window['name']} {name} {h}h needs both classes")
    return parts


def prepare(parts: dict) -> tuple[SimpleImputer, StandardScaler, dict]:
    if parts["train"][FEATURE_COLUMNS].isna().all().any():
        raise ValueError("Cannot fit median imputation to an entirely missing feature")
    imputer = SimpleImputer(strategy="median").fit(parts["train"][FEATURE_COLUMNS])
    matrices = {k: imputer.transform(p[FEATURE_COLUMNS]) for k, p in parts.items()}
    scaler = StandardScaler().fit(matrices["train"])
    settings = TrainingConfig()
    indices = [FEATURE_COLUMNS.index(c) for c in settings.baseline.features]
    baseline = {k: np.column_stack([
        compute_training_dryness(p, settings.dryness).to_numpy(),
        np.clip(scaler.transform(matrices[k]), -settings.baseline.z_score_clip,
                settings.baseline.z_score_clip)[:, indices],
    ]) for k, p in parts.items()}
    return imputer, scaler, {"primary": matrices, "baseline": baseline}


def make_model(spec: dict, seed: int):
    backend = spec["backend"]
    if backend in {"logistic_regression", "dryness_baseline"}:
        c = spec.get("c", 1.0)
        if c <= 0:
            raise ValueError("Logistic regularization C must be positive")
        logistic = LogisticRegression(C=c, class_weight="balanced", max_iter=1000, random_state=seed)
        return make_pipeline(StandardScaler(), logistic) if backend == "logistic_regression" else logistic
    if backend != "hist_gradient_boosting":
        raise ValueError(f"Unsupported experimental backend {backend}")
    params = {k: spec[k] for k in ("max_depth", "max_iter", "min_samples_leaf", "l2_regularization")}
    if min(params[k] for k in ("max_depth", "max_iter", "min_samples_leaf")) <= 0 or params["l2_regularization"] < 0:
        raise ValueError("Invalid boosting parameters")
    return HistGradientBoostingClassifier(**params, learning_rate=0.05,
        class_weight="balanced", random_state=seed, early_stopping=False)


def fit_model(spec: dict, seed: int, X: np.ndarray, y: np.ndarray):
    model = make_model(spec, seed)
    with warnings.catch_warnings():
        # sklearn 1.6 passes an option removed in this workstation's scipy.
        # Keep convergence warnings and other numerical failures visible.
        warnings.filterwarnings("ignore", message="Unknown solver options: iprint")
        model.fit(X, y)
    return model


def calibrate(base, X: np.ndarray, y: np.ndarray, horizon: int, method: str):
    # Export/use the fitted sklearn calibrator directly, with no legacy fallback.
    return build_calibrated_model(base, X, y, horizon, method=method).calibrator


def probability_metrics(y, probabilities) -> dict:
    y, p = np.asarray(y, dtype=int), np.asarray(probabilities, dtype=float)
    if not len(y) or p.shape != y.shape or not np.isfinite(p).all() or ((p < 0) | (p > 1)).any():
        raise ValueError("Expected nonempty aligned binary labels and finite probabilities")
    if not np.isin(y, [0, 1]).all():
        raise ValueError("Expected binary labels")
    both = len(np.unique(y)) == 2
    ap = float(average_precision_score(y, p)) if both else None
    thresholds = {}
    for cutoff in (0.35, 0.50, 0.60, 0.80):
        positive = p >= cutoff
        tp, fp = int(np.sum(positive & (y == 1))), int(np.sum(positive & (y == 0)))
        fn = int(np.sum(~positive & (y == 1)))
        thresholds[f"{cutoff:.2f}"] = {"precision": tp / (tp + fp) if tp + fp else 0.0,
            "recall": tp / (tp + fn) if tp + fn else 0.0,
            "tp": tp, "fp": fp, "fn": fn, "alert_rows": int(positive.sum())}
    bins = []
    for i in range(10):
        mask = (p >= i / 10) & ((p < (i + 1) / 10) if i < 9 else (p <= 1))
        if mask.any():
            bins.append({"lower": i / 10, "rows": int(mask.sum()),
                "mean_score": float(p[mask].mean()), "observed_rate": float(y[mask].mean())})
    prevalence = float(y.mean())
    return {"rows": len(y), "positives": int(y.sum()), "positive_rate": prevalence,
        "pr_auc": ap, "ap_lift_over_prevalence": ap / prevalence if ap is not None and prevalence else None,
        "roc_auc": float(roc_auc_score(y, p)) if both else None,
        "brier": float(brier_score_loss(y, p)),
        "score_quantiles": dict(zip(("min", "median", "p90", "max"), np.quantile(p, [0, .5, .9, 1]).tolist())),
        "thresholds": thresholds, "reliability_bins": bins}


def source_audit(path: Path, history: pd.DataFrame) -> dict:
    events = pd.read_parquet(path, columns=["cell_id", "ts", "satellite", "instrument", "confidence",
        "alert_eligible", "type", "source_file", "latitude", "longitude"])
    events = events.loc[events.cell_id.isin(set(history.cell_id))].copy()
    events["month"] = events.ts.str[:7]
    events["product"] = events.source_file.str.extract("(archive|nrt)", expand=False)
    monthly = events.groupby(["month", "product", "satellite"]).agg(
        detections=("ts", "size"), eligible=("alert_eligible", "sum")).reset_index()
    labels = history.assign(month=history.ts.str[:7]).groupby("month").agg(
        rows=("cell_id", "size"), positive_24h=("target_24h", "sum"), rate_24h=("target_24h", "mean")).reset_index()
    types = events.assign(type=events.type.fillna("unavailable")).groupby(["product", "type"]).size().reset_index(name="rows")
    return {"source": str(path), "instruments": events.instrument.value_counts().to_dict(),
        "satellites": events.satellite.value_counts().to_dict(),
        "duplicate_acquisition_keys": int(events.duplicated(["satellite", "ts", "latitude", "longitude"]).sum()),
        "detections_2025": int(events.month.str.startswith("2025").sum()),
        "monthly_events": monthly.to_dict("records"), "monthly_label_rates": labels.to_dict("records"),
        "fire_type_availability": types.to_dict("records"),
        "conclusion": "Both sources identify VIIRS N20/N21. The increase follows the archive/NRT boundary; its cause is not established. Labels and confidence filtering are unchanged. Export completeness is human-declared."}


def select_candidates(rows: list[dict], folds: list[str]) -> tuple[dict, list]:
    summary, selected = [], {}
    for h in HORIZONS:
        keys = sorted({r["key"] for r in rows if r["horizon_h"] == h})
        for key in keys:
            group = [r for r in rows if r["horizon_h"] == h and r["key"] == key]
            if sorted(r["fold"] for r in group) != sorted(folds):
                raise ValueError("Each candidate must have exactly one result per development fold")
            if any(r["validation"]["pr_auc"] is None for r in group):
                raise ValueError("Selection needs both classes in every development evaluation")
            summary.append({"horizon_h": h, "key": key, "spec": group[0]["spec"],
                "calibration": group[0]["calibration"], "eligible": group[0]["spec"]["backend"] != "dryness_baseline",
                "mean_pr_auc": float(np.mean([r["validation"]["pr_auc"] for r in group])),
                "mean_brier": float(np.mean([r["validation"]["brier"] for r in group]))})
        eligible = [r for r in summary if r["horizon_h"] == h and r["eligible"]]
        selected[str(h)] = sorted(eligible, key=lambda r: (-r["mean_pr_auc"], r["mean_brier"], r["key"]))[0]
    return selected, summary


def partition_summary(parts: dict) -> dict:
    return {name: {"rows": len(p), "start": p.ts.min(), "end": p.ts.max(),
        "positives": {str(h): int(p[f"target_{h}h"].sum()) for h in HORIZONS}} for name, p in parts.items()}


def export_bundle(folder, h, spec, method, base, calibrated, imputer, scaler, Xcal, ycal, metadata):
    settings = TrainingConfig()
    if spec["backend"] == "logistic_regression":
        raw = np.abs(base.named_steps["logisticregression"].coef_[0])
    else:
        raw = np.maximum(0, permutation_importance(base, Xcal, ycal, scoring="average_precision",
            n_repeats=3, max_samples=min(10000, len(ycal)), random_state=metadata["seed"]).importances_mean)
    priorities = np.array([settings.explanation.priority_multipliers.get(c, 1) for c in FEATURE_COLUMNS])
    raw *= priorities
    weights = raw / raw.sum() if raw.sum() else np.ones(len(raw)) / len(raw)
    signs = np.asarray(metadata["feature_signs"])
    bundle = {"horizon_h": h, "schema_version": SCHEMA_VERSION, "model_version": metadata["model_version"],
        "feature_columns": list(FEATURE_COLUMNS), "imputer": imputer, "scaler": scaler,
        "primary_model": calibrated, "model": calibrated, "base_primary": base,
        "signed_feature_weights": weights * signs, "feature_weights": weights * signs,
        "feature_signs": signs, "snapml_used": False,
        "training_data": metadata["training_data"], "experiment_spec": spec,
        "explanation_config": asdict(settings.explanation), "calibration_method": method}
    joblib.dump(bundle, folder / f"model_{h}h.joblib")


def run_experiment(plan: dict) -> dict:
    validate_plan(plan)
    resolve = lambda s: (PROJECT_ROOT / s).resolve()
    output = resolve(plan["output_dir"])
    # The experiment must never overlap source data, published models or feeds.
    allowed = (PROJECT_ROOT / "b_model/runs").resolve()
    if not output.is_relative_to(allowed) or output == allowed:
        raise ValueError("Experiment output must be a child of b_model/runs")
    if output.exists() and any(output.iterdir()):
        raise ValueError("Use a new empty output directory; do not rerun final evaluation while tuning")
    output.mkdir(parents=True, exist_ok=True)
    start = time.perf_counter()
    history, dropped = load_history(resolve(plan["history"]))
    metadata = {"started_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "history_sha256": hashlib.sha256(resolve(plan["history"]).read_bytes()).hexdigest(),
        "history_rows_used": len(history), "rows_with_incomplete_targets_dropped": dropped,
        "selection_rule": "Per horizon: largest mean calibrated development AP, then smallest mean Brier, then name. Baseline is a reference, not an eligible 27-feature primary.",
        "test_status": "Final-period metrics do not select candidates; aggregate source/monthly label counts were previously inspected.",
        "library_versions": {n: version(n) for n in ("numpy", "pandas", "scikit-learn", "joblib")}}
    OmegaConf.save(OmegaConf.create(plan), output / "protocol.yaml")
    write_json(output / "metadata.json", metadata)
    audit = source_audit(resolve(plan["events"]), history)
    write_json(output / "source_audit.json", audit)
    print(f"SOURCE: {audit['detections_2025']} detections in 2025; {audit['satellites']}", flush=True)
    baseline = {"name": "dryness_baseline", "backend": "dryness_baseline", "c": 1.0}
    rows = []
    for window in plan["development"]:
        parts = split_window(history, window)
        imputer, scaler, arrays = prepare(parts)
        write_json(output / f"split_{window['name']}.json", partition_summary(parts))
        for h in HORIZONS:
            ys = {k: p[f"target_{h}h"].to_numpy(dtype=int) for k, p in parts.items()}
            for spec in [baseline, *plan["candidates"]]:
                X = arrays["baseline" if spec["backend"] == "dryness_baseline" else "primary"]
                base = fit_model(spec, plan["seed"], X["train"], ys["train"])
                train_raw = probability_metrics(ys["train"], base.predict_proba(X["train"])[:, 1])
                raw_val = base.predict_proba(X["validation"])[:, 1]
                raw_metrics = probability_metrics(ys["validation"], raw_val)
                for method in plan["calibration_methods"]:
                    calibrated = calibrate(base, X["calibration"], ys["calibration"], h, method)
                    p = calibrated.predict_proba(X["validation"])[:, 1]
                    correlation = float(np.corrcoef(raw_val, p)[0, 1]) if np.std(p) > 0 and np.std(raw_val) > 0 else None
                    result = {"fold": window["name"], "horizon_h": h, "key": spec["name"] + "__" + method,
                        "spec": spec, "calibration": method, "train_raw": train_raw,
                        "validation_raw": raw_metrics, "validation": probability_metrics(ys["validation"], p),
                        "raw_calibrated_correlation": correlation}
                    rows.append(result)
                    print(f"DEV {window['name']} {h}h {result['key']}: AP={result['validation']['pr_auc']:.5f}", flush=True)
                write_json(output / "development.json", rows)
    selected, leaderboard = select_candidates(rows, [w["name"] for w in plan["development"]])
    # Persist decisions before any final-period model prediction/evaluation.
    write_json(output / "selection.json", {"selected": selected, "leaderboard": leaderboard})
    print("SELECTION FROZEN: " + json.dumps({h: s["key"] for h, s in selected.items()}), flush=True)
    parts = split_window(history, plan["final"])
    imputer, scaler, arrays = prepare(parts)
    write_json(output / "split_final.json", partition_summary(parts))
    model_dir = output / "model"
    model_dir.mkdir()
    final_results = {}
    model_version = "v1-experiment-" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    signs = compute_directional_feature_signs(arrays["primary"]["train"], parts["train"]["target_24h"].to_numpy())
    for h in HORIZONS:
        choice = selected[str(h)]
        X = arrays["primary"]
        ys = {k: p[f"target_{h}h"].to_numpy(dtype=int) for k, p in parts.items()}
        base = fit_model(choice["spec"], plan["seed"], X["train"], ys["train"])
        calibrated = calibrate(base, X["calibration"], ys["calibration"], h, choice["calibration"])
        probabilities = calibrated.predict_proba(X["validation"])[:, 1]
        no_recent = (parts["validation"].hotspots_in_cell_24h == 0).to_numpy()
        refs = [r for r in leaderboard if r["horizon_h"] == h and not r["eligible"]]
        reference = sorted(refs, key=lambda r: (-r["mean_pr_auc"], r["mean_brier"], r["key"]))[0]
        bX = arrays["baseline"]
        bbase = fit_model(baseline, plan["seed"], bX["train"], ys["train"])
        bcal = calibrate(bbase, bX["calibration"], ys["calibration"], h, reference["calibration"])
        previous = joblib.load(resolve(plan["previous_model_dir"]) / f"model_{h}h.joblib")
        previous_X = previous["imputer"].transform(parts["validation"][FEATURE_COLUMNS])
        persistence = parts["validation"].hotspots_in_cell_24h
        known = persistence.notna().to_numpy()
        final_results[str(h)] = {"selected": choice, "metrics": probability_metrics(ys["validation"], probabilities),
            "train_raw": probability_metrics(ys["train"], base.predict_proba(X["train"])[:, 1]),
            "no_recent_hotspots": probability_metrics(ys["validation"][no_recent], probabilities[no_recent]) if no_recent.any() else None,
            "dryness_baseline": probability_metrics(ys["validation"], bcal.predict_proba(bX["validation"])[:, 1]),
            "previous_published_candidate": probability_metrics(ys["validation"], previous["primary_model"].predict_proba(previous_X)[:, 1]),
            "persistence_rule": probability_metrics(ys["validation"][known], (persistence.to_numpy()[known] > 0).astype(float))}
        export_bundle(model_dir, h, choice["spec"], choice["calibration"], base, calibrated, imputer, scaler,
            X["calibration"], ys["calibration"], {"seed": plan["seed"], "model_version": model_version,
            "feature_signs": signs.tolist(), "training_data": metadata})
        print(f"FINAL {h}h AP={final_results[str(h)]['metrics']['pr_auc']:.5f}", flush=True)
    manifest = {"schema_version": SCHEMA_VERSION, "models": {str(h): {
        "filename": f"model_{h}h.joblib", "format": "joblib", "model_version": model_version,
        "feature_order": list(FEATURE_COLUMNS), "positive_class": 1} for h in HORIZONS}}
    write_json(model_dir / "artifact_manifest.json", manifest)
    write_json(output / "final_results.json", final_results)
    # Use PIC 1's existing consumer; published risk.json remains untouched.
    from b_model.predict import run_predictions
    inference_start = time.perf_counter()
    records = run_predictions(resolve(plan["features"]), model_dir, output / "risk.json", history_path=resolve(plan["history"]))
    result = {"metadata": metadata, "selected": selected, "final": final_results,
        "elapsed_seconds": time.perf_counter() - start, "inference_seconds": time.perf_counter() - inference_start,
        "replay_records": len(records), "replay_levels": pd.Series([r["risk_level"] for r in records]).value_counts().to_dict()}
    write_json(output / "results.json", result)
    print(f"COMPLETE: {output} ({result['elapsed_seconds']:.1f}s)", flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=PROJECT_ROOT / "b_model/conf/experiment.yaml")
    parser.add_argument("--output-dir", help="New experiment directory under b_model/runs")
    args = parser.parse_args()
    plan = OmegaConf.to_container(OmegaConf.load(args.config), resolve=True)
    if args.output_dir:
        plan["output_dir"] = args.output_dir
    run_experiment(plan)


if __name__ == "__main__":
    main()
