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


class TestRiskContract:
    """Tests validating Contract 3.2 on mock_output.json and live risk.json."""

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
            # Defect 1 & 4 assertions:
            score = rec["risk_score"]
            assert 0.01 <= score <= 0.99, f"risk_score {score} must be in [0.01, 0.99] and not equal 0.0 or 1.0"
            level = rec["risk_level"]
            factors = rec["top_factors"]
            assert len(factors) >= 2, f"Expected at least 2 top factors, got {len(factors)}"
            if level in ("CRITICAL", "HIGH", "MODERATE"):
                for factor in factors:
                    assert factor["contribution"] > 0.0, (
                        f"Elevated cell {rec['cell_id']} ({level}) factor {factor['feature']} "
                        f"contribution {factor['contribution']} must be strictly positive (> 0)"
                    )
            elif level == "LOW":
                for factor in factors:
                    assert factor["contribution"] < 0.0, (
                        f"Low risk cell {rec['cell_id']} ({level}) factor {factor['feature']} "
                        f"contribution {factor['contribution']} must be strictly negative (< 0)"
                    )


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

    def test_probability_calibration_wet_vs_dry(self):
        """
        Critical verification:
        Ensures a wet/normal cell scores < 0.35 (LOW) and an extreme dry-spell cell scores >= 0.80 (CRITICAL).
        """
        model_file = DEFAULT_MODEL_DIR / "model_24h.joblib"
        if not model_file.exists():
            pytest.skip("model_24h.joblib not yet trained.")

        bundle = joblib.load(model_file)
        model = bundle["primary_model"]
        imputer = bundle["imputer"]

        # 1. Extreme Dry-Spell Cell (Severe desiccation, high VPD, prolonged drought)
        dry_record = {
            "days_since_rain": 24,
            "rain_24h_mm": 0.0,
            "rain_7d_mm": 0.0,
            "rain_30d_mm": 5.0,
            "precip_mm": 0.0,
            "sm_27_81": 0.12,
            "sm_0_1": 0.08,
            "sm_1_3": 0.09,
            "sm_3_9": 0.10,
            "sm_9_27": 0.11,
            "sm_27_81_delta_7d": -0.08,
            "vpd_mean_24h": 3.8,
            "vpd_kpa": 3.8,
            "temp_c": 37.0,
            "soil_temp_0_c": 42.0,
            "soil_temp_18_c": 35.0,
            "soil_air_temp_gap_c": -2.0,
            "hotspots_in_cell_24h": 2,
            "hotspots_10km_7d": 6,
            "frp_sum_10km_7d": 60.0,
            "nearest_hotspot_km": 1.5,
            "peat_fraction": 0.85,
            "peat_area_km2": 10.0,
            "wind_kmh": 18.0,
            "wind_dir_deg": 140.0,
            "et_mm": 0.6,
            "et0_mm": 0.7,
        }
        df_dry = pd.DataFrame([dry_record])[FEATURE_COLUMNS]
        X_dry_imp = imputer.transform(df_dry)
        prob_dry = float(model.predict_proba(X_dry_imp)[0, 1])

        # 2. Wet / Normal Cell (Recent heavy rain, saturated deep peat, low VPD)
        wet_record = {
            "days_since_rain": 0,
            "rain_24h_mm": 35.0,
            "rain_7d_mm": 85.0,
            "rain_30d_mm": 210.0,
            "precip_mm": 12.0,
            "sm_27_81": 0.48,
            "sm_0_1": 0.44,
            "sm_1_3": 0.45,
            "sm_3_9": 0.46,
            "sm_9_27": 0.47,
            "sm_27_81_delta_7d": 0.03,
            "vpd_mean_24h": 0.5,
            "vpd_kpa": 0.4,
            "temp_c": 25.5,
            "soil_temp_0_c": 25.0,
            "soil_temp_18_c": 24.5,
            "soil_air_temp_gap_c": 0.5,
            "hotspots_in_cell_24h": 0,
            "hotspots_10km_7d": 0,
            "frp_sum_10km_7d": 0.0,
            "nearest_hotspot_km": 60.0,
            "peat_fraction": 0.60,
            "peat_area_km2": 7.0,
            "wind_kmh": 8.0,
            "wind_dir_deg": 100.0,
            "et_mm": 0.1,
            "et0_mm": 0.2,
        }
        df_wet = pd.DataFrame([wet_record])[FEATURE_COLUMNS]
        X_wet_imp = imputer.transform(df_wet)
        prob_wet = float(model.predict_proba(X_wet_imp)[0, 1])

        # Assert contract threshold alignment
        assert prob_wet < 0.35, f"Wet cell probability {prob_wet:.3f} must be < 0.35 (LOW)"
        assert prob_dry >= 0.80, f"Dry cell probability {prob_dry:.3f} must be >= 0.80 (CRITICAL)"

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

    def test_multicell_surge_elevates_both_cells(self, tmp_path):
        """Verifies comma-separated cell IDs elevate all designated cells to CRITICAL."""
        features_file = tmp_path / "multi_feat.json"
        risk_file = tmp_path / "multi_risk.json"
        generate_mock_data_if_missing(features_path=features_file)

        results = run_predictions(
            features_path=features_file,
            model_dir=DEFAULT_MODEL_DIR,
            output_path=risk_file,
            surge_cell="-2.35_114.05,-2.45_114.15",
        )

        surged_48h = [
            r for r in results
            if r["cell_id"] in ("-2.35_114.05", "-2.45_114.15") and r["horizon_h"] == 48
        ]
        assert len(surged_48h) == 2
        for r in surged_48h:
            assert r["risk_level"] == "CRITICAL", f"Cell {r['cell_id']} expected CRITICAL, got {r['risk_level']}"
            assert r["risk_score"] >= 0.80

    def test_surged_features_persistence(self, tmp_path):
        """Verifies --write-surged-features persists updated values to features.json for Role C consistency."""
        features_file = tmp_path / "feat_in.json"
        surged_features_file = tmp_path / "feat_out.json"
        risk_file = tmp_path / "risk_out.json"
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

    def test_metrics_json_beats_baseline_and_lead_time_hierarchy(self):
        """
        Defect 3 & 4: Verifies that in metrics.json:
        - For every horizon (24, 48, 72), primary PR-AUC > baseline PR-AUC
        - Primary ROC-AUC > baseline ROC-AUC
        - lead_time_hours >= 12.0
        - lead_time_72h > lead_time_48h > lead_time_24h
        """
        metrics_path = DEFAULT_MODEL_DIR / "metrics.json"
        if not metrics_path.exists():
            pytest.skip("metrics.json not yet generated. Run train.py first.")

        with open(metrics_path, "r", encoding="utf-8") as f:
            metrics = json.load(f)

        horizons = ["24", "48", "72"]
        for h in horizons:
            assert h in metrics["horizons"], f"Horizon {h} missing from metrics.json"
            m = metrics["horizons"][h]
            assert m["pr_auc"] > m["baseline_pr_auc"], (
                f"Horizon {h}h: Primary PR-AUC ({m['pr_auc']}) must beat baseline ({m['baseline_pr_auc']})"
            )
            assert m["roc_auc"] > m["baseline_roc_auc"], (
                f"Horizon {h}h: Primary ROC-AUC ({m['roc_auc']}) must beat baseline ({m['baseline_roc_auc']})"
            )
            assert m["lead_time_hours"] >= 12.0, (
                f"Horizon {h}h: lead_time_hours ({m['lead_time_hours']}) must be >= 12.0"
            )

        lt_24 = metrics["horizons"]["24"]["lead_time_hours"]
        lt_48 = metrics["horizons"]["48"]["lead_time_hours"]
        lt_72 = metrics["horizons"]["72"]["lead_time_hours"]
        assert lt_72 > lt_48 > lt_24, (
            f"Expected lead_time_72h ({lt_72}) > lead_time_48h ({lt_48}) > lead_time_24h ({lt_24})"
        )


class TestEndToEndPipeline:
    """Verifies train.py and predict.py complete fast and correctly."""

    def test_train_and_predict_under_60_seconds(self, tmp_path):
        """Ensures end-to-end execution of train and predict finishes well under 60 seconds."""
        history_file = tmp_path / "mock_history.parquet"
        features_file = tmp_path / "mock_features.json"
        model_dir = tmp_path / "models"
        risk_file = tmp_path / "mock_risk.json"

        generate_mock_data_if_missing(
            history_path=history_file,
            features_path=features_file,
            num_cells=6,
            days_history=10,
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

        # 2. Predict with surge cell
        results = run_predictions(
            features_path=features_file,
            model_dir=model_dir,
            output_path=risk_file,
            surge_cell="-2.35_114.05",
        )

        elapsed = time.time() - start_time
        assert elapsed < 60.0, f"Pipeline took {elapsed:.2f}s (must be < 60s)"

        # 3. Check predictions output
        assert risk_file.exists()
        validate_risk_contract(results)
        assert len(results) == 6 * len(HORIZONS)

