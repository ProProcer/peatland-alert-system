"""PIC 2 acceptance checks: config overrides reach fitting and survive inference."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys

from hydra import compose, initialize_config_dir
from hydra.errors import ConfigCompositionException
import joblib
import numpy as np
from omegaconf import OmegaConf
from omegaconf.errors import OmegaConfBaseException
import pandas as pd
import pytest

from b_model.config import FEATURE_COLUMNS, HORIZONS, PROJECT_ROOT
from b_model.features import compute_dryness_index, generate_mock_data_if_missing
from b_model.predict import run_predictions, validate_risk_contract
from b_model.train import compute_lead_time_hours, run_configured_training, temporal_train_calib_val_split
from b_model.training_config import DrynessSettings, TrainingConfig, compute_training_dryness, validate_training_config


def composed(overrides=()):
    with initialize_config_dir(config_dir=str(PROJECT_ROOT / "b_model/conf"), version_base="1.3"):
        return compose(config_name="training", overrides=list(overrides))


@pytest.mark.parametrize("backend", ["auto", "hist_gradient_boosting", "logistic_regression", "snapml"])
def test_composes_model_choices_with_typed_defaults(backend):
    settings = validate_training_config(composed([f"model={backend}", "model.learning_rate=0.12"]))
    assert settings.model.backend == backend
    assert settings.model.learning_rate == 0.12
    assert settings.split.strict_embargo
    assert settings.horizons == [24, 48, 72]


@pytest.mark.parametrize("override", [
    "model.learning_rate=-0.1", "model.max_iter=0", "model.max_depth=deep",
    "split.train_ratio=0.9", "split.embargo_hours=24", "split.strict_embargo=false",
    "dryness.rain_weight=0.9", "dryness.vpd_reference_kpa=0",
    "explanation.top_k=5", "explanation.importance_split=validation",
    "explanation.z_score_clip=3", "explanation.contribution_clip=0.6",
    "model.class_weight=unknown", "horizons=[24]", "seed=-1", "+unknown_setting=1",
    "+model.unknown_setting=1", "dryness.rain_weight=nan",
])
def test_rejects_invalid_or_incompatible_settings(override):
    with pytest.raises((ValueError, OmegaConfBaseException, ConfigCompositionException)):
        validate_training_config(composed([override]))


def test_dryness_overrides_change_a_hand_checkable_feature():
    frame = pd.DataFrame({"days_since_rain": [21, 30], "sm_27_81": [0.15, 0.50], "vpd_mean_24h": [2.8, 0.0]})
    result = compute_training_dryness(frame, DrynessSettings())
    assert result.iloc[0] == pytest.approx(0.72)
    np.testing.assert_allclose(result, compute_dryness_index(frame))
    changed = DrynessSettings(rain_weight=0.2, soil_weight=0.6, air_weight=0.2)
    assert compute_training_dryness(frame, changed).iloc[1] == pytest.approx(0.2)
    frame.loc[0, "vpd_mean_24h"] = np.nan
    frame["vpd_kpa"] = [2.8, 0]
    assert compute_training_dryness(frame, changed).notna().all()


def test_strict_split_preserves_both_embargoes_and_rejects_short_history():
    frame = pd.DataFrame({"ts": pd.date_range("2025-01-01", periods=30 * 24, freq="h", tz="UTC")})
    train, calibration, validation = temporal_train_calib_val_split(frame, strict_embargo=True)
    assert calibration.ts.min() - train.ts.max() >= pd.Timedelta(hours=72)
    assert validation.ts.min() - calibration.ts.max() >= pd.Timedelta(hours=72)
    with pytest.raises(ValueError, match="too short"):
        temporal_train_calib_val_split(frame.iloc[:240], strict_embargo=True)


@pytest.fixture(scope="module")
def historical_handoff(tmp_path_factory):
    folder = tmp_path_factory.mktemp("pic2-history")
    history, features = folder / "history.parquet", folder / "features.json"
    generate_mock_data_if_missing(history_path=history, features_path=features, num_cells=6, days_history=30, force=True)
    return history, features


@pytest.mark.parametrize("backend", ["hist_gradient_boosting", "logistic_regression"])
def test_training_overrides_are_saved_and_existing_inference_consumes_artifacts(backend, historical_handoff, tmp_path):
    history, features = historical_handoff
    before = hashlib.sha256(history.read_bytes()).hexdigest()
    settings = TrainingConfig()
    settings.paths.history = str(history)
    settings.paths.model_dir = str(tmp_path / "models")
    settings.model.backend = backend
    settings.model.max_iter = 6
    settings.model.max_depth = 2
    settings.model.logistic_c = 0.3
    settings.baseline.features = ["temp_c", "precip_mm"]
    settings.baseline.c = 0.4
    settings.dryness.rain_weight = 0.2
    settings.dryness.soil_weight = 0.6
    settings.explanation.permutation_repeats = 1
    metrics = run_configured_training(settings)
    model_dir = Path(settings.paths.model_dir)
    saved = OmegaConf.load(model_dir / "training_config.yaml")
    assert saved.model.backend == backend
    assert saved.dryness.soil_weight == 0.6
    assert metrics["training_data"]["sha256"] == before
    assert metrics["model_backend"] == backend
    assert metrics["training_config"]["split"]["strict_embargo"] is True
    assert set(metrics["horizons"]) == {"24", "48", "72"}
    manifest = json.loads((model_dir / "artifact_manifest.json").read_text())
    assert set(manifest["models"]) == {"24", "48", "72"}
    assert manifest["models"]["24"]["feature_order"] == FEATURE_COLUMNS
    for horizon in HORIZONS:
        artifact = joblib.load(model_dir / f"model_{horizon}h.joblib")
        assert artifact["feature_columns"] == FEATURE_COLUMNS
        assert artifact["baseline_feature_columns"] == ["dryness_index", "temp_c", "precip_mm"]
        assert artifact["baseline_model"].n_features_in_ == 3
        assert artifact["baseline_model"].C == 0.4
        assert artifact["dryness_config"]["rain_weight"] == 0.2
        assert artifact["explanation_config"]["permutation_repeats"] == 1
        assert not artifact["primary_model"].use_logit_scaling
        assert np.isfinite(artifact["signed_feature_weights"]).all()
        if backend == "hist_gradient_boosting":
            assert artifact["base_primary"].max_iter == 6
            assert artifact["base_primary"].max_depth == 2
            assert artifact["base_primary"].early_stopping is False
        else:
            assert artifact["base_primary"].named_steps["logisticregression"].C == 0.3
    predictions = run_predictions(features_path=features, history_path=history, model_dir=model_dir, output_path=tmp_path / "risk.json")
    validate_risk_contract(predictions)
    assert len(predictions) == 6 * 3
    assert hashlib.sha256(history.read_bytes()).hexdigest() == before


def test_missing_history_does_not_generate_mocks(tmp_path):
    settings = TrainingConfig()
    settings.paths.history = str(tmp_path / "missing.parquet")
    settings.paths.model_dir = str(tmp_path / "models")
    with pytest.raises(FileNotFoundError):
        run_configured_training(settings)
    assert list(tmp_path.iterdir()) == []


def test_empty_history_does_not_generate_mocks(tmp_path):
    settings = TrainingConfig()
    history = tmp_path / "empty.parquet"
    history.touch()
    settings.paths.history = str(history)
    settings.paths.model_dir = str(tmp_path / "models")
    with pytest.raises(ValueError, match="empty"):
        run_configured_training(settings)
    assert history.stat().st_size == 0
    assert not (tmp_path / "models").exists()


def test_missing_future_labels_are_rejected_instead_of_inferred_from_rolling_counts(historical_handoff, tmp_path):
    history, _ = historical_handoff
    frame = pd.read_parquet(history).drop(columns=["target_72h"])
    path = tmp_path / "missing-label.parquet"
    frame.to_parquet(path, index=False)
    settings = TrainingConfig()
    settings.paths.history = str(path)
    settings.paths.model_dir = str(tmp_path / "models")
    with pytest.raises(ValueError, match="producer-supplied future labels"):
        run_configured_training(settings)
    assert not (tmp_path / "models").exists()


def test_unobserved_lead_time_is_not_fabricated():
    frame = pd.DataFrame({"cell_id": ["-2.35_114.05"] * 4,
                          "ts": pd.date_range("2025-01-01", periods=4, freq="h", tz="UTC"),
                          "hotspots_in_cell_24h": [0] * 4})
    assert compute_lead_time_hours(frame, np.zeros(4), np.zeros(4), horizon_h=24) is None


def test_hydra_cli_renders_config_without_training_or_changing_working_directory(tmp_path):
    result = subprocess.run([sys.executable, "-m", "b_model.train", "--cfg", "job",
                             "model=logistic_regression", "model.logistic_c=0.25"],
                            cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert "backend: logistic_regression" in result.stdout
    assert "logistic_c: 0.25" in result.stdout
    assert "strict_embargo: true" in result.stdout
