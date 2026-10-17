"""Causal weather features, cold-start weighting and 29-predictor handoff."""
import json

import joblib
import numpy as np
import pandas as pd
import pytest

from b_model.config import FEATURE_COLUMNS, HORIZONS
from b_model.features import generate_mock_data_if_missing
from b_model.leading_indicators import (
    ENSEMBLE_FEATURES, PIPELINE_VERSION, add_leading_indicators,
    add_snapshot_indicators, cold_start_sample_weights,
)
from b_model.predict import load_artifact_manifest, run_predictions, validate_risk_contract
from b_model.train import run_configured_training
from b_model.training_config import TrainingConfig


def weather():
    times = pd.date_range("2025-01-01", periods=120, freq="h", tz="UTC")
    return pd.DataFrame({"cell_id": "-2.35_114.05", "ts": times,
                         "precip_mm": 0.0, "sm_27_81": np.arange(120) / 1000})


def test_daily_rain_and_momentum_are_causal_and_cell_specific():
    frame = weather()
    frame.loc[24, "precip_mm"] = 1.0
    result = add_leading_indicators(frame)
    assert np.isnan(result.loc[22, "cumulative_dry_days"])
    assert result.loc[23, "cumulative_dry_days"] == 1
    assert result.loc[24, "cumulative_dry_days"] == 1  # day not complete yet
    assert result.loc[47, "cumulative_dry_days"] == 0  # exactly 1 mm is wet
    assert result.loc[71, "cumulative_dry_days"] == 1
    assert result.loc[72, "soil_moisture_momentum"] == pytest.approx(0.072 - 0.0355)
    changed = frame.copy()
    changed.loc[73:, ["precip_mm", "sm_27_81"]] = 500.0
    pd.testing.assert_frame_equal(add_leading_indicators(changed).iloc[:73], result.iloc[:73])
    other = frame.copy()
    other["cell_id"], other["precip_mm"], other["sm_27_81"] = "b", 5.0, 0.1
    mixed = pd.concat([frame, other], ignore_index=True).sample(frac=1, random_state=1)
    combined = add_leading_indicators(mixed)
    pd.testing.assert_frame_equal(combined.loc[frame.index].sort_index(), result)


def test_gaps_and_null_measurements_are_not_dry_zeros():
    frame = weather().drop(index=48)
    frame.loc[10, "sm_27_81"] = np.nan
    result = add_leading_indicators(frame)
    assert np.isnan(result.loc[71, "cumulative_dry_days"])
    assert np.isnan(result.loc[72, "soil_moisture_momentum"])
    with pytest.raises(ValueError, match="Duplicate"):
        add_leading_indicators(pd.concat([frame, frame.iloc[:1]]))


def test_weights_train_frequency_and_unknown_history():
    frame = pd.DataFrame({"hotspots_in_cell_24h": [0, 2, np.nan, 0, 2, 0, 0]})
    labels = np.array([1, 1, 1, 0, 0, 0, 0])
    weights, report = cold_start_sample_weights(frame, labels)
    np.testing.assert_allclose(weights, [20 / 3, 4 / 3, 4 / 3, 1, 1, 1, 1])
    assert report["cold_start_positive_rows"] == 1
    with pytest.raises(ValueError, match="both"):
        cold_start_sample_weights(frame, np.zeros(7))


def test_snapshot_ignores_future_history_and_matches_training(tmp_path):
    frame = weather()
    snapshot = frame.iloc[[95]].copy().reset_index(drop=True)
    history = tmp_path / "history.parquet"
    frame.to_parquet(history)
    actual = add_snapshot_indicators(snapshot, history)
    expected = add_leading_indicators(frame).loc[95, ENSEMBLE_FEATURES[-2:]].astype(float)
    np.testing.assert_allclose(actual[ENSEMBLE_FEATURES[-2:]].iloc[0], expected)
    frame.loc[96:, ["precip_mm", "sm_27_81"]] = 999
    frame.to_parquet(history)
    pd.testing.assert_frame_equal(add_snapshot_indicators(snapshot, history), actual)
    with pytest.raises(ValueError, match="history"):
        add_snapshot_indicators(snapshot, None)


@pytest.mark.parametrize("backend", ["xgboost", "auto", "snapml"])
def test_ensemble_training_roundtrip_and_fallback(backend, tmp_path, monkeypatch):
    import b_model.train as training
    from xgboost import XGBClassifier
    seen = {}
    if backend == "snapml":
        # Verify Snap constructor wiring without claiming hardware execution.
        def snap_constructor(**kwargs):
            seen.update(kwargs)
            return XGBClassifier(n_estimators=3, max_depth=2, n_jobs=2)
        monkeypatch.setattr(training, "SNAPML_AVAILABLE", True)
        monkeypatch.setattr(training, "SnapBoostingMachineClassifier", snap_constructor, raising=False)
    else:
        monkeypatch.setattr(training, "SNAPML_AVAILABLE", False)
    history, features = tmp_path / "history.parquet", tmp_path / "features.json"
    generate_mock_data_if_missing(history_path=history, features_path=features,
                                 num_cells=3, days_history=30, force=True)
    settings = TrainingConfig()
    settings.paths.history, settings.paths.model_dir = str(history), str(tmp_path / "models")
    settings.model.backend, settings.model.max_iter = backend, 3
    metrics = run_configured_training(settings)
    manifest = load_artifact_manifest(tmp_path / "models")
    assert metrics["model_backend"] == ("snapml" if backend == "snapml" else "xgboost")
    for horizon in HORIZONS:
        entry, path = manifest[horizon]
        assert entry["feature_order"] == ENSEMBLE_FEATURES
        assert entry["feature_pipeline"] == PIPELINE_VERSION
        artifact = joblib.load(path)
        assert artifact["imputer"].n_features_in_ == 29
        assert artifact["sample_weighting"]["cold_start_multiplier"] == 5
        assert "quiet_case" in metrics["horizons"][str(horizon)]
    if backend == "snapml":
        assert seen["class_weight"] is None
        assert seen["colsample_bytree"] == 0.7
    else:
        assert artifact["base_primary"].get_params()["scale_pos_weight"] == 1
        assert artifact["base_primary"].get_params()["colsample_bytree"] == 0.7
    risk = run_predictions(features_path=features, history_path=history,
                           model_dir=tmp_path / "models", output_path=tmp_path / "risk.json")
    assert len(risk) == 9
    validate_risk_contract(risk)
    assert all(factor["feature"] in FEATURE_COLUMNS for row in risk for factor in row["top_factors"])
    data = json.loads((tmp_path / "models/artifact_manifest.json").read_text())
    del data["models"]["24"]["feature_pipeline"]
    (tmp_path / "models/artifact_manifest.json").write_text(json.dumps(data))
    with pytest.raises(ValueError, match="feature_order"):
        load_artifact_manifest(tmp_path / "models")
