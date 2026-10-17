"""Checks for temporal leakage, selection isolation and consumer compatibility."""

import copy
import json
from pathlib import Path

import numpy as np
from omegaconf import OmegaConf
import pandas as pd
import pytest
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler

from b_model.config import FEATURE_COLUMNS, HORIZONS, PROJECT_ROOT
from b_model.experiment import (calibrate, export_bundle, fit_model, load_history,
    prepare, probability_metrics, select_candidates, split_window, validate_plan)


def history():
    t = pd.date_range("2025-01-01", periods=24 * 16, freq="h", tz="UTC")
    df = pd.DataFrame({c: np.ones(len(t)) for c in FEATURE_COLUMNS})
    df["cell_id"], df["ts"] = "-2.35_114.05", t.strftime("%Y-%m-%dT%H:%M:%SZ")
    df["_time"] = t
    for h in HORIZONS:
        df[f"target_{h}h"] = np.arange(len(t)) % 2
    return df


WINDOW = dict(name="test", train_end="2025-01-04T00:00:00Z",
    calibration_start="2025-01-07T00:00:00Z", calibration_end="2025-01-09T00:00:00Z",
    validation_start="2025-01-12T00:00:00Z", validation_end="2025-01-16T00:00:00Z")


def test_protocol_reserves_final_period_and_full_embargo():
    plan = OmegaConf.to_container(OmegaConf.load(PROJECT_ROOT / "b_model/conf/experiment.yaml"), resolve=True)
    validate_plan(plan)
    bad = copy.deepcopy(plan)
    bad["development"][-1]["validation_end"] = "2026-09-05T00:00:00Z"
    with pytest.raises(ValueError, match="Development evaluation"):
        validate_plan(bad)
    bad = copy.deepcopy(plan)
    bad["final"]["calibration_start"] = bad["final"]["train_end"]
    with pytest.raises(ValueError, match="embargo"):
        validate_plan(bad)


def test_split_purges_labels_and_keeps_preprocessing_on_training():
    df = history()
    df.loc[df._time >= WINDOW["calibration_start"], "temp_c"] = 1000
    df.loc[df._time < WINDOW["train_end"], "temp_c"] = np.tile([1.0, np.nan], 36)
    parts = split_window(df, WINDOW)
    assert parts["train"]._time.max() + pd.Timedelta(hours=72) < parts["calibration"]._time.min()
    assert parts["calibration"]._time.max() + pd.Timedelta(hours=72) < parts["validation"]._time.min()
    imputer, _, matrices = prepare(parts)
    i = FEATURE_COLUMNS.index("temp_c")
    assert imputer.statistics_[i] == 1.0
    assert matrices["primary"]["validation"][:, i].min() == 1000


def test_incomplete_labels_are_dropped_and_invalid_labels_rejected(tmp_path):
    df = history().drop(columns="_time")
    df.loc[0, "target_72h"] = np.nan
    path = tmp_path / "history.parquet"
    df.to_parquet(path, index=False)
    usable, dropped = load_history(path)
    assert dropped == 1 and len(usable) == len(df) - 1
    df.loc[1, "target_24h"] = 2
    df.to_parquet(path, index=False)
    with pytest.raises(ValueError, match="Labels"):
        load_history(path)


def test_selection_requires_all_development_folds():
    rows = [{"key": key, "horizon_h": h, "fold": fold,
        "spec": {"backend": "logistic_regression"}, "calibration": "sigmoid",
        "validation": {"pr_auc": ap, "brier": .1}}
        for h in HORIZONS for fold in ("earlier", "later") for key, ap in (("a", .2), ("b", .3))]
    selected, _ = select_candidates(rows, ["earlier", "later"])
    assert all(r["key"] == "b" for r in selected.values())
    with pytest.raises(ValueError, match="exactly one"):
        select_candidates(rows[:-1], ["earlier", "later"])


def test_metrics_preserve_fixed_thresholds_and_single_class_status():
    result = probability_metrics([0, 1, 1, 1], [.349, .35, .60, .80])
    assert result["thresholds"]["0.35"]["tp"] == 3
    assert result["thresholds"]["0.60"]["tp"] == 2
    assert result["thresholds"]["0.80"]["tp"] == 1
    assert probability_metrics([0, 0], [.1, .2])["pr_auc"] is None
    with pytest.raises(ValueError):
        probability_metrics([0, 1], [float("nan"), .4])


def test_export_is_accepted_by_actual_pic1_inference(tmp_path):
    from b_model.predict import run_predictions
    from b_model.features import generate_mock_data_if_missing

    rng = np.random.default_rng(42)
    raw = pd.DataFrame(rng.normal(size=(120, len(FEATURE_COLUMNS))), columns=FEATURE_COLUMNS)
    y = (raw.temp_c > 0).to_numpy(dtype=int)
    imputer = SimpleImputer(strategy="median").fit(raw.iloc[:80])
    train, cal = imputer.transform(raw.iloc[:80]), imputer.transform(raw.iloc[80:])
    scaler = StandardScaler().fit(train)
    spec = {"name": "test", "backend": "logistic_regression", "c": .01}
    models = tmp_path / "models"
    models.mkdir()
    for h in HORIZONS:
        base = fit_model(spec, 42, train, y[:80])
        calibrated = calibrate(base, cal, y[80:], h, "sigmoid")
        export_bundle(models, h, spec, "sigmoid", base, calibrated, imputer, scaler, cal, y[80:],
            {"seed": 42, "model_version": "test-experiment", "feature_signs": [1] * len(FEATURE_COLUMNS), "training_data": {}})
    (models / "artifact_manifest.json").write_text(json.dumps({"schema_version": "1.0", "models": {
        str(h): {"filename": f"model_{h}h.joblib", "format": "joblib", "model_version": "test-experiment",
            "feature_order": FEATURE_COLUMNS, "positive_class": 1} for h in HORIZONS}}))
    features_path = tmp_path / "features.json"
    generate_mock_data_if_missing(history_path=tmp_path / "history.parquet", features_path=features_path,
        num_cells=3, days_history=4, force=True)
    result = run_predictions(features_path, models, tmp_path / "risk.json", history_path=None)
    assert len(result) == 9
    assert {r["model_version"] for r in result} == {"test-experiment"}


def test_extended_xgboost_export_is_portable_and_runs_actual_inference(tmp_path):
    from xgboost import XGBClassifier
    from b_model.leading_indicators import ENSEMBLE_FEATURES, PIPELINE_VERSION
    from b_model.portable_xgboost import PortableBooster
    from b_model.predict import run_predictions
    from b_model.features import generate_mock_data_if_missing
    rng=np.random.default_rng(12)
    raw=pd.DataFrame(rng.normal(size=(120,29)),columns=ENSEMBLE_FEATURES)
    y=(raw.temp_c>0).to_numpy(dtype=int)
    imputer=SimpleImputer(strategy='median').fit(raw.iloc[:80])
    train,cal=imputer.transform(raw.iloc[:80]),imputer.transform(raw.iloc[80:])
    models=tmp_path/'models';models.mkdir()
    for h in HORIZONS:
        base=XGBClassifier(n_estimators=3,max_depth=2,n_jobs=2).fit(train,y[:80])
        calibrated=calibrate(base,cal,y[80:],h,'sigmoid')
        expected=calibrated.predict_proba(cal)
        export_bundle(models,h,{'backend':'xgboost'},'sigmoid',base,calibrated,imputer,
            StandardScaler().fit(train),cal,y[80:],{'seed':42,'model_version':'test-ensemble',
                'feature_signs':[1]*29,'training_data':{}},feature_columns=ENSEMBLE_FEATURES)
        import joblib
        loaded=joblib.load(models/f'model_{h}h.joblib')
        assert isinstance(loaded['base_primary'].get_booster(),PortableBooster)
        np.testing.assert_array_equal(loaded['primary_model'].predict_proba(cal),expected)
    (models/'artifact_manifest.json').write_text(json.dumps({'schema_version':'1.0','models':{
        str(h):{'filename':f'model_{h}h.joblib','format':'joblib','model_version':'test-ensemble',
            'feature_order':ENSEMBLE_FEATURES,'positive_class':1,'feature_pipeline':PIPELINE_VERSION}
        for h in HORIZONS}}))
    features,history=tmp_path/'features.json',tmp_path/'history.parquet'
    generate_mock_data_if_missing(features_path=features,history_path=history,num_cells=3,days_history=4,force=True)
    result=run_predictions(features,models,tmp_path/'risk.json',history_path=history)
    assert len(result)==9
    assert all(f['feature'] in FEATURE_COLUMNS for r in result for f in r['top_factors'])
