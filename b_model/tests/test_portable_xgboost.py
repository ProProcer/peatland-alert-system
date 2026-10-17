"""Verify stable model export and trusted uploaded-manifest migration."""

import json

import joblib
import numpy as np
import pytest
from xgboost import XGBClassifier

from b_model.config import HORIZONS
from b_model.leading_indicators import ENSEMBLE_FEATURES, PIPELINE_VERSION
from b_model.portable_xgboost import PortableBooster
from b_model.repair_artifacts import repair


def test_portable_model_roundtrip_preserves_predictions(tmp_path):
    rng = np.random.default_rng(7)
    values = rng.normal(size=(100, 29))
    labels = (values[:, 0] > 0).astype(int)
    model = XGBClassifier(n_estimators=4, max_depth=2, n_jobs=2).fit(values, labels)
    expected = model.predict_proba(values)
    booster = model.get_booster()
    booster.__class__ = PortableBooster
    assert set(booster.__getstate__()) == {"portable_model"}
    path = tmp_path / "portable.joblib"
    joblib.dump(model, path)
    loaded = joblib.load(path)
    np.testing.assert_array_equal(loaded.predict_proba(values), expected)


def test_repair_preserves_supplied_keys_and_validates_all_bundles(tmp_path):
    pytest.importorskip("ubjson")
    rng = np.random.default_rng(8)
    values = rng.normal(size=(100, 29))
    labels = (values[:, 0] > 0).astype(int)
    model = XGBClassifier(n_estimators=4, max_depth=2, n_jobs=2).fit(values, labels)
    expected = model.predict_proba(values)
    model_dir, backup = tmp_path / "models", tmp_path / "backup"
    model_dir.mkdir()
    supplied = {"model_version": "supplied-version", "feature_order": ["unmatched"],
                "format": "joblib", "horizons": ["24", "48", "72"]}
    manifest_path = model_dir / "artifact_manifest.json"
    manifest_path.write_text(json.dumps(supplied))
    original_bytes = {}
    for horizon in HORIZONS:
        path = model_dir / f"model_{horizon}h.joblib"
        joblib.dump({"schema_version": "1.0", "horizon_h": horizon,
                     "model_version": "v1", "feature_columns": ENSEMBLE_FEATURES,
                     "feature_pipeline": PIPELINE_VERSION, "primary_model": model}, path)
        original_bytes[path.name] = path.read_bytes()
    report = repair(model_dir, backup)
    manifest = json.loads(manifest_path.read_text())
    assert all(manifest[key] == value for key, value in supplied.items())
    assert manifest["schema_version"] == "1.0"
    assert json.loads((backup / "original/artifact_manifest.json").read_text()) == supplied
    for horizon in HORIZONS:
        name = f"model_{horizon}h.joblib"
        assert (backup / "original" / name).read_bytes() == original_bytes[name]
        assert manifest["models"][str(horizon)]["feature_order"] == ENSEMBLE_FEATURES
        assert report["horizons"][str(horizon)]["boosters"][0]["all_model_fields_preserved"]
        recovered = joblib.load(model_dir / name)
        assert isinstance(recovered["primary_model"].get_booster(), PortableBooster)
        np.testing.assert_array_equal(recovered["primary_model"].predict_proba(values), expected)
    with pytest.raises(ValueError, match="backup"):
        repair(model_dir, backup)
