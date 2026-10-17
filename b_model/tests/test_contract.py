"""
Contract validation and end-to-end test suite for Role B (ML Lead).
Enforces Team Playbook Contracts 3.1 & 3.2.
"""

from datetime import datetime
import json
from pathlib import Path
import sys
import time

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import joblib
import numpy as np
import pandas as pd
import pytest

from b_model.config import (
    DEFAULT_FEATURES_PATH,
    DEFAULT_HISTORY_PATH,
    DEFAULT_MOCK_OUTPUT_PATH,
    DEFAULT_MODEL_DIR,
    DEFAULT_RISK_PATH,
    DOMAIN_FEATURE_SIGNS,
    FEATURE_COLUMNS,
    HORIZONS,
    MODEL_VERSION,
    SCHEMA_VERSION,
    get_risk_level,
)
from b_model.features import (
    compute_dryness_index,
    flatten_feature_record,
    flatten_features_json,
    generate_mock_data_if_missing,
)
from b_model.predict import (
    apply_surge_scenario,
    compute_local_attributions,
    run_predictions,
    validate_risk_contract,
)
from b_model.train import temporal_train_val_split, train_pipeline


def _validate_single_risk_record(rec: dict):
    # Required keys
    expected_keys = {
        "schema_version",
        "cell_id",
        "ts",
        "horizon_h",
        "risk_score",
        "risk_level",
        "top_factors",
        "model_version",
    }
    assert set(rec.keys()) == expected_keys, f"Keys mismatch: {rec.keys()}"

    # Types and values
    assert rec["schema_version"] == SCHEMA_VERSION
    assert rec["model_version"] == MODEL_VERSION
    assert isinstance(rec["cell_id"], str) and len(rec["cell_id"]) > 0

    # Horizon
    assert rec["horizon_h"] in {24, 48, 72}

    # Score and level
    score = rec["risk_score"]
    assert isinstance(score, (int, float))
    assert 0.0 <= score <= 1.0
    assert rec["risk_level"] == get_risk_level(score)

    # Timestamp
    ts = rec["ts"]
    assert isinstance(ts, str) and ts.endswith("Z"), f"Timestamp {ts} must end with Z"
    parsed_ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    assert parsed_ts is not None

    # Top factors
    tf = rec["top_factors"]
    assert isinstance(tf, list) and len(tf) >= 1
    for factor in tf:
        assert isinstance(factor, dict)
        assert "feature" in factor and "contribution" in factor
        assert isinstance(factor["feature"], str)
        assert isinstance(factor["contribution"], (int, float))
        assert factor["feature"] in FEATURE_COLUMNS, f"Unknown feature in factor: {factor['feature']}"


class ConstantProbabilityModel:
    """Deterministic test double; not an evaluated forecasting model."""
    def __init__(self, probability, reverse_classes=False):
        self.probability = probability
        self.classes_ = np.array([1, 0] if reverse_classes else [0, 1])

    def predict_proba(self, values):
        probabilities = [self.probability if c == 1 else 1 - self.probability for c in self.classes_]
        return np.tile(probabilities, (len(values), 1))


def write_test_artifacts(model_dir, probability=0.5, serialization="joblib", reverse_order=False,
                         reverse_classes=False):
    """Create a minimal manifest-backed handoff without retraining or touching saved models."""
    import pickle
    from sklearn.impute import SimpleImputer
    from sklearn.preprocessing import StandardScaler
    model_dir.mkdir(parents=True, exist_ok=True)
    order = list(reversed(FEATURE_COLUMNS)) if reverse_order else list(FEATURE_COLUMNS)
    imputer = SimpleImputer(strategy="median").fit(pd.DataFrame(np.zeros((2, len(order))), columns=order))
    scaler = StandardScaler().fit(np.zeros((2, len(order))))
    manifest = {"schema_version": "1.0", "models": {}}
    for horizon in HORIZONS:
        filename = f"custom-{horizon}.{'pkl' if serialization == 'pickle' else 'joblib'}"
        manifest["models"][str(horizon)] = {
            "filename": filename, "format": serialization, "model_version": "test-v2",
            "feature_order": order, "positive_class": 1,
        }
        bundle = {
            "horizon_h": horizon, "schema_version": "1.0", "model_version": "test-v2",
            "feature_columns": order, "imputer": imputer, "scaler": scaler,
            "primary_model": ConstantProbabilityModel(probability, reverse_classes),
            "signed_feature_weights": np.ones(len(order)) * 0.1,
        }
        if serialization == "pickle":
            with (model_dir / filename).open("wb") as handle:
                pickle.dump(bundle, handle)
        else:
            joblib.dump(bundle, model_dir / filename)
    (model_dir / "artifact_manifest.json").write_text(json.dumps(manifest))
    return manifest


class TestRiskContract:
    """Tests validating Contract 3.2 on mock_output.json and live risk.json."""

    @pytest.mark.parametrize("field,value", [
        ("ts", "2026-02-30T09:00:00Z"),
        ("ts", "2026-10-17T09:00:00+00:00"),
        ("cell_id", "114.05_-2.35"),
        ("risk_score", float("nan")),
        ("risk_score", True),
        ("risk_score", -999),
        ("horizon_h", 24.0),
        ("risk_level", "LOW"),
    ])
    def test_reject_invalid_risk(self, field, value):
        records = json.loads(DEFAULT_MOCK_OUTPUT_PATH.read_text())
        records[0][field] = value
        with pytest.raises(ValueError):
            validate_risk_contract(records)

    def test_reject_nonfinite_and_sentinel_factors(self):
        for value in (-999, float("inf"), float("nan"), True):
            records = json.loads(DEFAULT_MOCK_OUTPUT_PATH.read_text())
            records[0]["top_factors"][0]["contribution"] = value
            with pytest.raises(ValueError):
                validate_risk_contract(records)

    def test_reject_duplicate_risks_and_extra_fields(self):
        records = json.loads(DEFAULT_MOCK_OUTPUT_PATH.read_text())
        with pytest.raises(ValueError):
            validate_risk_contract(records + [records[0]])
        records[0]["scores"] = {}
        with pytest.raises(ValueError):
            validate_risk_contract(records)

    def test_risk_level_boundaries(self):
        """Tests exact threshold definitions: LOW < 0.35 <= MODERATE < 0.60 <= HIGH < 0.80 <= CRITICAL."""
        assert get_risk_level(0.0) == "LOW"
        assert get_risk_level(0.34) == "LOW"
        assert get_risk_level(0.3499) == "LOW"

        assert get_risk_level(0.35) == "MODERATE"
        assert get_risk_level(0.50) == "MODERATE"
        assert get_risk_level(0.59) == "MODERATE"
        assert get_risk_level(0.5999) == "MODERATE"

        assert get_risk_level(0.60) == "HIGH"
        assert get_risk_level(0.70) == "HIGH"
        assert get_risk_level(0.79) == "HIGH"
        assert get_risk_level(0.7999) == "HIGH"

        assert get_risk_level(0.80) == "CRITICAL"
        assert get_risk_level(0.95) == "CRITICAL"
        assert get_risk_level(1.0) == "CRITICAL"

    def test_mock_output_json_adheres_to_contract_3_2(self):
        """Verifies b_model/mock_output.json strictly adheres to Contract 3.2."""
        assert DEFAULT_MOCK_OUTPUT_PATH.exists(), f"Missing {DEFAULT_MOCK_OUTPUT_PATH}"
        with open(DEFAULT_MOCK_OUTPUT_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)

        assert isinstance(data, list) and len(data) > 0
        validate_risk_contract(data)

        cells = {"-2.35_114.05", "-2.45_114.15", "-2.55_114.25"}
        for cell in cells:
            cell_records = [r for r in data if r["cell_id"] == cell]
            assert len(cell_records) == 3, f"Cell {cell} missing horizons in mock_output.json"
            cell_horizons = {r["horizon_h"] for r in cell_records}
            assert cell_horizons == {24, 48, 72}

        for rec in data:
            _validate_single_risk_record(rec)

    def test_live_risk_json_adheres_to_contract_3_2(self):
        """Verifies data/processed/risk.json strictly adheres to Contract 3.2."""
        if not DEFAULT_RISK_PATH.exists():
            pytest.skip("data/processed/risk.json not yet generated.")

        with open(DEFAULT_RISK_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)

        assert isinstance(data, list) and len(data) > 0
        validate_risk_contract(data)

        for rec in data:
            _validate_single_risk_record(rec)
            assert 1 <= len(rec["top_factors"]) <= 3
            assert all(np.isfinite(factor["contribution"]) for factor in rec["top_factors"])



class TestFeatureContract:
    """Tests validating Contract 3.1 flattening, deduplication, and feature integrity."""

    def test_flatten_feature_record(self):
        """Tests flattening logic ignores polygon_ids and converts nulls to np.nan."""
        mock_record = {
            "schema_version": "1.0",
            "cell_id": "-2.35_114.05",
            "ts": "2026-10-17T09:00:00Z",
            "lat": -2.35,
            "lon": 114.05,
            "peat": {
                "peat_fraction": 0.62,
                "peat_area_km2": 7.4,
                "polygon_ids": ["{GUID-123}", "{GUID-456}"],
            },
            "weather": {
                "temp_c": 33.1,
                "precip_mm": 0.0,
                "wind_kmh": 11.4,
                "wind_dir_deg": 125,
                "sm_0_1": 0.18,
                "sm_1_3": None,
                "sm_3_9": 0.21,
                "sm_9_27": 0.24,
                "sm_27_81": 0.28,
                "vpd_kpa": 2.1,
                "soil_temp_0_c": 36.0,
                "soil_temp_18_c": 31.4,
                "et_mm": 0.3,
                "et0_mm": 0.4,
            },
            "derived": {
                "rain_24h_mm": 0.0,
                "rain_7d_mm": 3.2,
                "rain_30d_mm": 41.0,
                "days_since_rain": 9,
                "sm_27_81_delta_7d": -0.04,
                "vpd_mean_24h": 1.9,
                "soil_air_temp_gap_c": -1.7,
            },
            "fire": {
                "hotspots_in_cell_24h": 0,
                "hotspots_10km_7d": 4,
                "frp_sum_10km_7d": 18.3,
                "nearest_hotspot_km": 6.2,
            },
        }

        flat = flatten_feature_record(mock_record)
        assert "polygon_ids" not in flat
        assert np.isnan(flat["sm_1_3"])
        assert flat["et0_mm"] == 0.4
        assert flat["cell_id"] == "-2.35_114.05"

    def test_flatten_features_canonical_columns(self, tmp_path):
        """Verifies DataFrame output contains all 27 FEATURE_COLUMNS in exact order."""
        features_file = tmp_path / "test_features.json"
        generate_mock_data_if_missing(features_path=features_file, force=True)

        df = flatten_features_json(features_file)
        for col in FEATURE_COLUMNS:
            assert col in df.columns, f"Missing feature column: {col}"

    def test_multihour_deduplication(self, tmp_path):
        """Verifies flatten_features_json keeps only latest timestamp per cell_id when latest_only=True."""
        multi_records = []
        for hour in ["08:00:00Z", "09:00:00Z", "10:00:00Z"]:
            for cell in ["-2.35_114.05", "-2.45_114.15"]:
                multi_records.append({
                    "schema_version": "1.0",
                    "cell_id": cell,
                    "ts": f"2026-10-17T{hour}",
                    "lat": float(cell.split("_")[0]),
                    "lon": float(cell.split("_")[1]),
                    "peat": {"peat_fraction": 0.6, "peat_area_km2": 7.0},
                    "weather": {"temp_c": 30.0, "precip_mm": 0.0, "sm_27_81": 0.3},
                    "derived": {"days_since_rain": 5, "vpd_mean_24h": 1.5},
                    "fire": {"hotspots_in_cell_24h": 0},
                })
        json_file = tmp_path / "multihour.json"
        with open(json_file, "w") as f:
            json.dump(multi_records, f)

        # Supply the complete frozen structure; absent measurements are explicit nulls.
        from b_model.config import FEATURE_GROUPS
        for record in multi_records:
            record["peat"]["polygon_ids"] = []
            for group, columns in FEATURE_GROUPS.items():
                for column in columns:
                    record[group].setdefault(column, None)
        json_file.write_text(json.dumps(multi_records))

        # 6 records in, exactly 2 unique cells out with timestamp 10:00:00Z
        df_dedup = flatten_features_json(json_file, latest_only=True)
        assert len(df_dedup) == 2
        assert set(df_dedup["cell_id"]) == {"-2.35_114.05", "-2.45_114.15"}
        for _, row in df_dedup.iterrows():
            assert row["ts"] == "2026-10-17T10:00:00Z"

    def test_compute_dryness_index(self):
        """Verifies dryness index is strictly bounded within [0.0, 1.0]."""
        test_df = pd.DataFrame({
            "days_since_rain": [0, 15, 30, 45, np.nan],
            "sm_27_81": [0.55, 0.35, 0.15, 0.05, np.nan],
            "vpd_mean_24h": [0.5, 1.5, 3.5, 5.0, np.nan],
        })
        dryness = compute_dryness_index(test_df)
        assert len(dryness) == 5
        assert (dryness >= 0.0).all()
        assert (dryness <= 1.0).all()
        assert dryness.iloc[2] > dryness.iloc[0]


class TestMLCorrectnessAndCalibration:
    """Verifies ML correctness, probability calibration, embargo gaps, and directional feature signs."""

    def test_saved_model_uses_its_actual_feature_pipeline(self, tmp_path):
        """Exercise real inference with either 27 or 29 artifact predictors."""
        from b_model.leading_indicators import ENSEMBLE_FEATURES
        source, history = tmp_path / "features.json", tmp_path / "history.parquet"
        generate_mock_data_if_missing(features_path=source, history_path=history,
                                      num_cells=3, days_history=4, force=True)
        bundle = joblib.load(DEFAULT_MODEL_DIR / "model_24h.joblib")
        order = bundle["feature_columns"]
        assert order in (FEATURE_COLUMNS, ENSEMBLE_FEATURES)
        assert list(bundle["imputer"].feature_names_in_) == order
        predictions = run_predictions(source, DEFAULT_MODEL_DIR, tmp_path / "risk.json",
                                      history_path=history)
        assert len(predictions) == 9
        validate_risk_contract(predictions)
        # Prediction probability is measured, never forced by a dry scenario.

    def test_directional_feature_attribution_signs(self):
        """
        Verifies directional signed attribution:
        - Low deep moisture (sm_27_81 < 0) yields positive contribution to fire danger
        - High rainfall (rain_24h_mm > 0) yields negative contribution (risk suppression)
        - Prolonged dry spell (days_since_rain > 0) yields positive contribution
        """
        # Feature indices
        sm_idx = FEATURE_COLUMNS.index("sm_27_81")
        rain_idx = FEATURE_COLUMNS.index("rain_24h_mm")
        dry_idx = FEATURE_COLUMNS.index("days_since_rain")

        # Mock signed weights
        signed_weights = np.ones(len(FEATURE_COLUMNS)) * 0.10
        signed_weights[sm_idx] = -0.20  # sm_* has negative sign
        signed_weights[rain_idx] = -0.25  # rain_* has negative sign
        signed_weights[dry_idx] = 0.30  # days_since_rain has positive sign

        # Mock standardized vector for drought condition:
        # sm_27_81 is depleted: z = -2.0
        # rain_24h_mm is zero (below mean): z = -1.5
        # days_since_rain is high (above mean): z = +2.5
        X_scaled = np.zeros((1, len(FEATURE_COLUMNS)))
        X_scaled[0, sm_idx] = -2.0
        X_scaled[0, dry_idx] = 2.5

        factors = compute_local_attributions(
            model=None,
            X_imp=X_scaled,
            X_scaled=X_scaled,
            signed_feature_weights=signed_weights,
            feature_names=FEATURE_COLUMNS,
            top_k=3,
        )[0]

        factor_map = {f["feature"]: f["contribution"] for f in factors}
        # Low soil moisture must have POSITIVE risk contribution (-2.0 * -0.20 = +0.40)
        assert "sm_27_81" in factor_map
        assert factor_map["sm_27_81"] > 0, "Depleted sm_27_81 must contribute positively to fire risk"

        # Days since rain must have POSITIVE risk contribution (+2.5 * +0.30 = +0.75)
        assert "days_since_rain" in factor_map
        assert factor_map["days_since_rain"] > 0, "Prolonged dry days must contribute positively to fire risk"

    def test_temporal_split_72h_embargo(self):
        """Verifies temporal split enforces a 72-hour purge gap between train and validation sets."""
        timestamps = pd.date_range("2025-08-01 00:00:00", periods=20 * 24, freq="1h", tz="UTC")
        df_dummy = pd.DataFrame({
            "cell_id": "test_cell",
            "ts": [t.strftime("%Y-%m-%dT%H:%M:%SZ") for t in timestamps],
            "hotspots_in_cell_24h": 0,
        })

        df_train, df_val = temporal_train_val_split(df_dummy, train_ratio=0.80, embargo_hours=72)
        max_train_ts = pd.to_datetime(df_train["ts"].max())
        min_val_ts = pd.to_datetime(df_val["ts"].min())

        gap_hours = (min_val_ts - max_train_ts).total_seconds() / 3600.0
        assert gap_hours >= 72.0, f"Embargo gap {gap_hours:.1f}h must be at least 72 hours"

    def test_simulate_surge_cell(self):
        """Verifies apply_surge_scenario injects an extreme dry spell into the designated cell."""
        df_base = pd.DataFrame([{
            "cell_id": "-2.55_114.25",
            "ts": "2026-10-17T09:00:00Z",
            "days_since_rain": 0,
            "precip_mm": 10.0,
            "sm_27_81": 0.45,
            "vpd_mean_24h": 0.5,
        }])
        df_surged = apply_surge_scenario(df_base, "-2.55_114.25")
        row = df_surged[df_surged["cell_id"] == "-2.55_114.25"].iloc[0]
        assert row["days_since_rain"] == 25
        assert row["sm_27_81"] == 0.12
        assert row["vpd_mean_24h"] == 3.8

    def test_cli_negative_cell_id_with_space(self, tmp_path):
        """Verifies CLI argument normalization prevents argparse crashes on negative latitude cell_ids."""
        from b_model.predict import main, normalize_cli_args

        # 1. Test normalize_cli_args directly with negative cell ID preceded by space
        raw_cli = ["--surge-cell", "-2.55_114.25", "--model-dir", str(DEFAULT_MODEL_DIR)]
        normalized = normalize_cli_args(raw_cli)
        assert "--surge-cell=-2.55_114.25" in normalized

        # 2. Test running main() with space-separated negative cell_id
        features_file = tmp_path / "feat.json"
        risk_file = tmp_path / "risk.json"
        generate_mock_data_if_missing(features_path=features_file)

        # Calling main with list of args containing space-separated negative cell_id must not crash
        main([
            "--input", str(features_file),
            "--output", str(risk_file),
            "--model-dir", str(DEFAULT_MODEL_DIR),
            "--surge-cell", "-2.55_114.25",
        ])
        assert risk_file.exists()

    def test_multicell_surge_applies_to_both_cells_without_forcing_scores(self, tmp_path):
        """Scenario changes reach both cells and leave the other inputs intact."""
        features_file = tmp_path / "multi_feat.json"
        risk_file = tmp_path / "risk.json"
        history = tmp_path / "history.parquet"
        persisted = tmp_path / "surged_features.json"
        generate_mock_data_if_missing(features_path=features_file, history_path=history,
                                      num_cells=3, days_history=4, force=True)
        before = {r['cell_id']: r for r in json.loads(features_file.read_text())}
        targets = sorted(before)[:2]

        results = run_predictions(
            features_path=features_file,
            model_dir=DEFAULT_MODEL_DIR,
            output_path=risk_file,
            surge_cell=','.join(targets),
            history_path=history,
            write_surged_features=True,
            surge_output_features=persisted,
        )

        surged_48h = [
            r for r in results
            if r["cell_id"] in targets and r["horizon_h"] == 48
        ]
        assert len(surged_48h) == 2
        validate_risk_contract(results)
        after = {r['cell_id']: r for r in json.loads(persisted.read_text())}
        for cell in targets:
            assert after[cell]['derived']['days_since_rain'] == 25
            assert after[cell]['weather']['sm_27_81'] == 0.12
            assert after[cell]['derived']['vpd_mean_24h'] == 3.8
        for cell in set(before) - set(targets):
            assert after[cell] == before[cell]

    def test_surged_features_persistence(self, tmp_path):
        """Verifies --write-surged-features persists updated values to features.json for Role C consistency."""
        features_file = tmp_path / "feat_in.json"
        surged_features_file = tmp_path / "feat_out.json"
        risk_file = tmp_path / "risk.json"
        generate_mock_data_if_missing(features_path=features_file)

        run_predictions(
            features_path=features_file,
            model_dir=DEFAULT_MODEL_DIR,
            output_path=risk_file,
            surge_cell="-2.55_114.25",
            write_surged_features=True,
            surge_output_features=surged_features_file,
        )

        assert surged_features_file.exists()
        with open(surged_features_file, "r") as f:
            data = json.load(f)

        surged_records = [r for r in data if r["cell_id"] == "-2.55_114.25"]
        assert len(surged_records) == 1
        surged_rec = surged_records[0]
        assert surged_rec["weather"]["sm_27_81"] == 0.12
        assert surged_rec["derived"]["days_since_rain"] == 25
        assert surged_rec["derived"]["vpd_mean_24h"] == 3.8

    def test_sparse_satellite_data_calibration_compression_guard(self):
        """
        Simulates extremely sparse satellite data (~3% base rate).
        Verifies that the compression guard ensures wet cells stay < 0.35 (LOW)
        and extreme drought cells still reach >= 0.80 (CRITICAL).
        """
        from b_model.train import build_calibrated_model
        from sklearn.ensemble import HistGradientBoostingClassifier

        rng = np.random.RandomState(42)
        n = 2000
        days_dry = rng.randint(0, 25, n)
        sm_27 = np.clip(0.45 - days_dry * 0.015 + rng.normal(0, 0.03, n), 0.12, 0.50)
        vpd = np.clip(0.8 + days_dry * 0.1 + rng.normal(0, 0.2, n), 0.4, 3.8)

        # 3% overall positive rate
        dryness = 0.4 * (days_dry / 25.0) + 0.4 * (1.0 - sm_27 / 0.5) + 0.2 * (vpd / 3.5)
        prob = 0.002 + 0.08 * (dryness ** 4)
        y = (rng.rand(n) < prob).astype(int)
        assert y.mean() < 0.05, f"Expected sparse positive rate < 5%, got {y.mean():.3f}"

        X = np.zeros((n, len(FEATURE_COLUMNS)))
        col_idx = {c: i for i, c in enumerate(FEATURE_COLUMNS)}
        X[:, col_idx["days_since_rain"]] = days_dry
        X[:, col_idx["sm_27_81"]] = sm_27
        X[:, col_idx["vpd_mean_24h"]] = vpd

        train_split = int(n * 0.70)
        calib_split = int(n * 0.85)

        X_train, y_train = X[:train_split], y[:train_split]
        X_calib, y_calib = X[train_split:calib_split], y[train_split:calib_split]

        base = HistGradientBoostingClassifier(class_weight="balanced", random_state=42)
        base.fit(X_train, y_train)

        # Build calibrated model with compression guard
        calibrated_model = build_calibrated_model(
            base_primary=base,
            X_calib_imp=X_calib,
            y_calib=y_calib,
            horizon_h=24,
        )

        # Test on wet vs extreme drought cells
        wet_sample = np.zeros((1, len(FEATURE_COLUMNS)))
        wet_sample[0, col_idx["days_since_rain"]] = 0
        wet_sample[0, col_idx["sm_27_81"]] = 0.48
        wet_sample[0, col_idx["vpd_mean_24h"]] = 0.5

        dry_sample = np.zeros((1, len(FEATURE_COLUMNS)))
        dry_sample[0, col_idx["days_since_rain"]] = 25
        dry_sample[0, col_idx["sm_27_81"]] = 0.12
        dry_sample[0, col_idx["vpd_mean_24h"]] = 3.8

        p_wet = float(calibrated_model.predict_proba(wet_sample)[0, 1])
        p_dry = float(calibrated_model.predict_proba(dry_sample)[0, 1])

        assert p_wet < 0.35, f"Sparse data wet cell expected < 0.35, got {p_wet:.3f}"
        assert p_dry >= 0.80, f"Sparse data extreme drought cell expected >= 0.80, got {p_dry:.3f}"

    def test_saved_metrics_are_valid_and_acceptance_is_reported_separately(self):
        """Validate measurements; poor models must be rejected by the quality gate."""
        from b_model.quality import assess_saved_metrics
        metrics = json.loads((DEFAULT_MODEL_DIR / "metrics.json").read_text())
        report = assess_saved_metrics(metrics)
        assert set(report["horizons"]) == {"24", "48", "72"}
        for h, result in report["horizons"].items():
            measured = metrics["horizons"][h]
            expected = (measured["pr_auc"] is not None
                        and measured["baseline_pr_auc"] is not None
                        and measured["pr_auc"] > measured["baseline_pr_auc"]
                        and measured["recall"] > 0)
            assert result["accepted"] == expected
            assert bool(result["reasons"]) != expected
        assert report["accepted"] == all(r["accepted"] for r in report["horizons"].values())


class TestHydraInference:
    """Inference acceptance checks independent of claimed training quality."""

    @pytest.fixture
    def inputs(self, tmp_path):
        source = tmp_path / "features.json"
        history = tmp_path / "history.parquet"
        generate_mock_data_if_missing(features_path=source, history_path=history,
                                      num_cells=3, days_history=2)
        return source, history

    def test_latest_null_is_not_backfilled_from_an_older_hour(self, inputs):
        source, _ = inputs
        records = json.loads(source.read_text())
        newer = json.loads(json.dumps(records[0]))
        newer["ts"] = "2026-10-17T10:00:00Z"
        newer["weather"]["sm_27_81"] = None
        source.write_text(json.dumps(records + [newer]))
        df = flatten_features_json(source)
        latest = df.loc[df.cell_id == newer["cell_id"]].iloc[0]
        assert latest.ts == newer["ts"]
        assert pd.isna(latest.sm_27_81)

    def test_history_predictor_columns_and_dtypes(self, inputs):
        source, history = inputs
        reference = pd.read_parquet(history).drop(columns=["target_24h", "target_48h", "target_72h"])
        actual = flatten_features_json(source, history_path=history)
        assert actual.columns.tolist() == reference.columns.tolist()
        assert actual.dtypes.equals(reference.dtypes)

    @pytest.mark.parametrize("bad_value", [-999, float("nan"), float("inf"), "bad", True])
    def test_reject_bad_measurements(self, inputs, bad_value):
        source, _ = inputs
        records = json.loads(source.read_text())
        records[0]["weather"]["temp_c"] = bad_value
        source.write_text(json.dumps(records))
        with pytest.raises(ValueError):
            flatten_features_json(source)

    def test_missing_input_does_not_create_mock_files(self, tmp_path):
        source = tmp_path / "absent.json"
        with pytest.raises(FileNotFoundError):
            flatten_features_json(source)
        assert not source.exists()

    def test_structured_config_validation(self):
        from omegaconf import OmegaConf
        from omegaconf.errors import OmegaConfBaseException
        from b_model.config import validate_config
        for invalid in ({"horizons": [24]}, {"paths": {"output": "other.json"}},
                        {"max_seconds": 61}, {"imputation": {"continuous": "zero"}}):
            with pytest.raises(ValueError):
                validate_config(OmegaConf.create(invalid))
        for invalid in ({"typo": 1}, {"max_seconds": "invalid"}):
            with pytest.raises(OmegaConfBaseException):
                validate_config(OmegaConf.create(invalid))

    def test_nullable_counts_are_imputed_without_modifying_json(self, inputs, tmp_path):
        source, history = inputs
        from b_model.predict import run_configured
        from omegaconf import OmegaConf
        records = json.loads(source.read_text())
        records[0]["fire"]["hotspots_in_cell_24h"] = None
        records[0]["weather"]["sm_27_81"] = None
        source.write_text(json.dumps(records))
        before = source.read_bytes()
        for strategy in ("artifact_median", "zero"):
            output = tmp_path / strategy / "risk.json"
            summary = run_configured(OmegaConf.create({
                "paths": {"features": str(source), "history": str(history),
                          "model_dir": str(DEFAULT_MODEL_DIR), "output": str(output)},
                "imputation": {"hotspot_counts": strategy},
            }))
            validate_risk_contract(json.loads(output.read_text()))
            assert set(summary[records[0]["cell_id"]]["scores"]) == set(HORIZONS)
        assert source.read_bytes() == before

    def test_hydra_cli_300_cells_under_60_seconds(self, inputs, tmp_path):
        import os
        import subprocess
        source, history = inputs
        template = json.loads(source.read_text())[0]
        records = []
        for index in range(300):
            record = json.loads(json.dumps(template))
            record["lat"] = round(-2.35 - (index // 30) * 0.1, 2)
            record["lon"] = round(114.05 + (index % 30) * 0.1, 2)
            record["cell_id"] = f'{record["lat"]:.2f}_{record["lon"]:.2f}'
            records.append(record)
        source.write_text(json.dumps(records))
        output = tmp_path / "risk.json"
        env = dict(os.environ, OMP_NUM_THREADS="2", OPENBLAS_NUM_THREADS="2")
        start = time.perf_counter()
        result = subprocess.run([
            sys.executable, "-m", "b_model.predict", f"paths.features={source.as_posix()}",
            f"paths.history={history.as_posix()}", f"paths.output={output.as_posix()}",
        ], cwd=PROJECT_ROOT, env=env, capture_output=True, text=True, timeout=60)
        assert result.returncode == 0, result.stdout + result.stderr
        assert time.perf_counter() - start < 60
        payload = json.loads(output.read_text())
        assert len(payload) == 900
        validate_risk_contract(payload)
        assert {r["cell_id"] for r in payload} == {r["cell_id"] for r in records}

    @pytest.mark.parametrize("group,key", [("fire", "temp_c"), ("weather", "cell_id"), ("peat", "ts")])
    def test_reject_cross_group_overwrite(self, inputs, group, key):
        source, _ = inputs
        records = json.loads(source.read_text())
        records[0][group][key] = -999
        source.write_text(json.dumps(records))
        with pytest.raises(ValueError, match=rf"record\[0\].{group}.{key}: unexpected"):
            flatten_features_json(source)
        with pytest.raises(ValueError):
            flatten_feature_record(records[0])

    @pytest.mark.parametrize("replacement", [None, [], "invalid", 12])
    def test_nested_types_have_context(self, inputs, replacement):
        source, _ = inputs
        records = json.loads(source.read_text())
        records[1]["fire"] = replacement
        source.write_text(json.dumps(records))
        with pytest.raises(ValueError, match=r"record\[1\].fire: expected an object"):
            flatten_features_json(source)

    def test_missing_fields_and_nonobject_rows_have_context(self, inputs):
        source, _ = inputs
        records = json.loads(source.read_text())
        del records[0]["weather"]["temp_c"]
        source.write_text(json.dumps(records))
        with pytest.raises(ValueError, match=r"record\[0\].weather.temp_c: required"):
            flatten_features_json(source)
        source.write_text("[null]")
        with pytest.raises(ValueError, match=r"record\[0\]"):
            flatten_features_json(source)

    @pytest.mark.parametrize("field,value", [("peat_fraction", 0.01), ("peat_fraction", None)])
    def test_reject_invalid_peat_metadata(self, inputs, field, value):
        source, _ = inputs
        records = json.loads(source.read_text())
        records[0]["peat"][field] = value
        source.write_text(json.dumps(records))
        with pytest.raises(ValueError, match="peat.peat_fraction"):
            flatten_features_json(source)

    @pytest.mark.parametrize("dtype,value", [("int8", 200), ("uint8", -1), ("uint8", 256), ("int64", float(2**63))])
    def test_integer_overflow_rejected(self, inputs, tmp_path, dtype, value):
        from b_model.features import align_history_schema
        source, _ = inputs
        frame = flatten_features_json(source).drop(columns="schema_version")
        reference = frame.copy()
        reference["hotspots_in_cell_24h"] = 0
        reference["hotspots_in_cell_24h"] = reference["hotspots_in_cell_24h"].astype(dtype)
        history = tmp_path / "typed.parquet"
        reference.to_parquet(history, index=False)
        frame.loc[0, "hotspots_in_cell_24h"] = value
        with pytest.raises(ValueError, match="integer exceeds"):
            align_history_schema(frame, history)

    def test_nullable_unsigned_integer_and_float_overflow(self, inputs, tmp_path):
        from b_model.features import align_history_schema
        source, _ = inputs
        frame = flatten_features_json(source).drop(columns="schema_version")
        reference = frame.copy()
        reference["hotspots_in_cell_24h"] = reference["hotspots_in_cell_24h"].astype("uint8")
        reference["temp_c"] = reference["temp_c"].astype("float32")
        history = tmp_path / "typed.parquet"
        reference.to_parquet(history, index=False)
        frame.loc[0, "hotspots_in_cell_24h"] = np.nan
        assert str(align_history_schema(frame, history)["hotspots_in_cell_24h"].dtype) == "UInt8"
        frame.loc[0, "temp_c"] = 1e40
        with pytest.raises(ValueError, match="floating-point overflow"):
            align_history_schema(frame, history)

    def test_attribution_is_exact_and_not_sign_filtered(self):
        values = np.zeros((1, len(FEATURE_COLUMNS)))
        weights = np.zeros(len(FEATURE_COLUMNS))
        factors = compute_local_attributions(None, values, values, weights, FEATURE_COLUMNS)
        assert all(f["contribution"] == 0 for f in factors[0])
        values[0, :3] = [5, -4, 0.0001]
        weights[:3] = [0.3, 0.2, 0.7]
        for risk in (0.1, 0.9):
            factors = compute_local_attributions(None, values, values, weights, FEATURE_COLUMNS,
                                                 risk_scores=np.array([risk]))[0]
            assert [f["feature"] for f in factors] == FEATURE_COLUMNS[:3]
            assert [f["contribution"] for f in factors] == list(values[0, :3] * weights[:3])

    @pytest.mark.parametrize("probability,level", [
        (0.0, "LOW"), (0.349, "LOW"), (0.35, "MODERATE"), (0.599, "MODERATE"),
        (0.60, "HIGH"), (0.799, "HIGH"), (0.80, "CRITICAL"), (1.0, "CRITICAL"),
    ])
    def test_unrounded_probability_handoff(self, inputs, tmp_path, probability, level):
        source, history = inputs
        models = tmp_path / "models"
        write_test_artifacts(models, probability)
        output = tmp_path / "risk.json"
        results = run_predictions(source, models, output, history_path=history)
        saved = json.loads(output.read_text())
        assert saved == results
        assert all(r["risk_score"] == probability and r["risk_level"] == level for r in saved)
        assert all(r["model_version"] == "test-v2" for r in saved)
        validate_risk_contract(saved)

    @pytest.mark.parametrize("serialization", ["pickle", "joblib"])
    def test_manifest_formats_feature_order_and_positive_class(self, inputs, tmp_path, serialization):
        source, history = inputs
        models = tmp_path / "models"
        write_test_artifacts(models, 0.7, serialization, reverse_order=True, reverse_classes=True)
        results = run_predictions(source, models, tmp_path / "risk.json", history_path=history)
        assert all(r["risk_score"] == 0.7 and r["risk_level"] == "HIGH" for r in results)

    @pytest.mark.parametrize("field,value", [
        ("filename", "../outside.pkl"), ("format", "unknown"),
        ("feature_order", FEATURE_COLUMNS[:-1]), ("model_version", ""),
    ])
    def test_reject_bad_manifest(self, inputs, tmp_path, field, value):
        from b_model.predict import load_artifact_manifest
        models = tmp_path / "models"
        manifest = write_test_artifacts(models)
        manifest["models"]["24"][field] = value
        (models / "artifact_manifest.json").write_text(json.dumps(manifest))
        with pytest.raises(ValueError):
            load_artifact_manifest(models)

    def test_model_metadata_mismatch_does_not_publish(self, inputs, tmp_path):
        source, history = inputs
        models = tmp_path / "models"
        manifest = write_test_artifacts(models)
        manifest["models"]["24"]["model_version"] = "wrong"
        (models / "artifact_manifest.json").write_text(json.dumps(manifest))
        output = tmp_path / "risk.json"
        with pytest.raises(ValueError, match="model_version"):
            run_predictions(source, models, output, history_path=history)
        assert not output.exists()

    def test_serialization_failure_preserves_outputs_and_inputs(self, inputs, tmp_path, monkeypatch):
        import b_model.predict as inference
        source, history = inputs
        models = tmp_path / "models"
        write_test_artifacts(models)
        output = tmp_path / "risk.json"
        output.write_text('["previous complete output"]')
        before = source.read_bytes(), output.read_bytes(), history.read_bytes()
        def partial_write(*args, **kwargs):
            args[1].write('[{"partial":')
            raise TypeError("serialization failed")
        monkeypatch.setattr(inference.json, "dump", partial_write)
        with pytest.raises(TypeError, match="serialization failed"):
            run_predictions(source, models, output, history_path=history)
        assert (source.read_bytes(), output.read_bytes(), history.read_bytes()) == before
        assert not list(tmp_path.glob(".risk-*.tmp"))

    def test_missing_models_cannot_mutate_surged_input(self, inputs, tmp_path):
        source, history = inputs
        before = source.read_bytes()
        demo = tmp_path / "demo-features.json"
        with pytest.raises(FileNotFoundError):
            run_predictions(source, tmp_path / "absent", tmp_path / "risk.json",
                            surge_cell="-2.35_114.05", surge_output_features=demo, history_path=history)
        assert source.read_bytes() == before
        assert not demo.exists()

    def test_input_collisions_and_unknown_surge_are_rejected(self, inputs, tmp_path):
        source, history = inputs
        before = source.read_bytes()
        with pytest.raises(ValueError, match="overwrite inputs"):
            run_predictions(source, DEFAULT_MODEL_DIR, tmp_path / "risk.json", history_path=history,
                            surge_cell="-2.35_114.05", surge_output_features=source)
        with pytest.raises(ValueError, match="separate"):
            run_predictions(source, DEFAULT_MODEL_DIR, tmp_path / "risk.json", history_path=history,
                            surge_cell="-2.35_114.05", write_surged_features=True)
        with pytest.raises(ValueError, match="Unknown surge cell"):
            run_predictions(source, DEFAULT_MODEL_DIR, tmp_path / "risk.json", history_path=history,
                            surge_cell="-3.05_115.05")
        assert source.read_bytes() == before

    def test_demo_feed_matches_inference_transformation(self, inputs, tmp_path):
        source, history = inputs
        before = source.read_bytes()
        demo = tmp_path / "demo-features.json"
        run_predictions(source, DEFAULT_MODEL_DIR, tmp_path / "risk.json", history_path=history,
                        surge_cell="-2.35_114.05", surge_output_features=demo)
        expected = apply_surge_scenario(flatten_features_json(source), "-2.35_114.05")
        actual = flatten_features_json(demo)
        pd.testing.assert_frame_equal(actual, expected)
        assert source.read_bytes() == before

    def test_legacy_cli_uses_yaml_environment_and_shared_checks(self, inputs, tmp_path, monkeypatch):
        from b_model.predict import main
        source, history = inputs
        output = tmp_path / "risk.json"
        monkeypatch.setenv("PEAT_FEATURES", str(source))
        monkeypatch.setenv("PEAT_HISTORY", str(history))
        monkeypatch.setenv("PEAT_RISK", str(output))
        main(["--model-dir", str(DEFAULT_MODEL_DIR)])
        validate_risk_contract(json.loads(output.read_text()))
        risk_source = tmp_path / "input" / "risk.json"
        risk_source.parent.mkdir()
        risk_source.write_bytes(source.read_bytes())
        before = risk_source.read_bytes()
        with pytest.raises(SystemExit):
            main(["--input", str(risk_source), "--output", str(risk_source)])
        assert risk_source.read_bytes() == before


class TestEndToEndPipeline:
    """Verifies train.py and predict.py complete fast and correctly."""

    def test_train_and_predict_under_60_seconds(self, tmp_path):
        """Ensures end-to-end execution of train and predict finishes well under 60 seconds."""
        history_file = tmp_path / "mock_history.parquet"
        features_file = tmp_path / "mock_features.json"
        model_dir = tmp_path / "models"
        risk_file = tmp_path / "risk.json"

        generate_mock_data_if_missing(
            history_path=history_file,
            features_path=features_file,
            num_cells=6,
            days_history=30,
            force=True,
        )

        start_time = time.time()

        # 1. Train
        metrics = train_pipeline(
            history_path=history_file,
            model_dir=model_dir,
            force_mock=False,
        )
        assert "horizons" in metrics
        for h in HORIZONS:
            assert str(h) in metrics["horizons"]
            m = metrics["horizons"][str(h)]
            assert "pr_auc" in m
            assert "roc_auc" in m
            assert "lead_time_hours" in m

        # PIC 2 publishes a manifest alongside the newly trained bundles.
        assert (model_dir / "artifact_manifest.json").is_file()

        # 2. Predict with surge cell
        results = run_predictions(
            features_path=features_file,
            model_dir=model_dir,
            output_path=risk_file,
            history_path=history_file,
            surge_cell="-2.35_114.05",
        )

        elapsed = time.time() - start_time
        assert elapsed < 60.0, f"Pipeline took {elapsed:.2f}s (must be < 60s)"

        # 3. Check predictions output
        assert risk_file.exists()
        validate_risk_contract(results)
        assert len(results) == 6 * len(HORIZONS)

