"""Repair a trusted uploaded manifest and export portable inference boosters.

Conversion-only dependency: py-ubjson. Original bundles and the supplied manifest
are backed up before any replacements. No fitting or probability changes occur.
"""

import argparse
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import shutil
from unittest.mock import patch

import joblib
import numpy as np
from xgboost import Booster

from b_model.config import FEATURE_COLUMNS, HORIZONS, SCHEMA_VERSION
from b_model.leading_indicators import ENSEMBLE_FEATURES, PIPELINE_VERSION
from b_model.portable_xgboost import PortableBooster
from b_model.predict import load_artifact_manifest


@contextmanager
def recover_portable_boosters(audits):
    """Explicit, single-process migration of trusted UBJSON memory snapshots.

    Decode the full snapshot with a real UBJSON parser and retain its Model
    object through the public stable loader. Ignore Config (including OS-specific
    RNG state); verify that every model field/tree survives the round trip.
    Never install this patch in the production inference path.
    """
    import ubjson

    def restore(self, state):
        if set(state) != {"handle"}:
            raise ValueError("Unexpected legacy Booster state")
        snapshot = ubjson.loadb(bytes(state["handle"]))
        if not isinstance(snapshot, dict) or set(snapshot) != {"Config", "Model"}:
            raise ValueError("Expected a complete XGBoost Config/Model snapshot")
        model = snapshot["Model"]
        self.__class__ = PortableBooster
        # UBJSON optimized uint8 arrays decode as bytes; stable JSON represents
        # those categorical/index arrays as integer lists.
        def json_array(value):
            if isinstance(value, (bytes, bytearray)):
                return list(value)
            raise TypeError(f"Unsupported UBJSON model value: {type(value).__name__}")

        self.__setstate__({"portable_model": json.dumps(model, default=json_array, allow_nan=False).encode("utf-8")})
        recovered = ubjson.loadb(bytes(self.save_raw(raw_format="ubj")))
        if recovered != model:
            raise ValueError("Portable model does not exactly preserve the stored model trees/parameters")
        audits.append({"model_version": model["version"], "all_model_fields_preserved": True})

    with patch.object(Booster, "__setstate__", restore):
        yield


def repair(model_dir: Path, backup_dir: Path):
    model_dir, backup_dir = model_dir.resolve(), backup_dir.resolve()
    if backup_dir.exists():
        raise ValueError("Use a new backup directory; existing backups are never overwritten")
    manifest_path = model_dir / "artifact_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    original = backup_dir / "original"
    staged = backup_dir / "converted"
    original.mkdir(parents=True)
    staged.mkdir()
    shutil.copy2(manifest_path, original / manifest_path.name)
    # Back up all three originals before deserialization/conversion.
    for horizon in HORIZONS:
        name = f"model_{horizon}h.joblib"
        shutil.copy2(model_dir / name, original / name)
    entries, report = {}, {"mode": "portable_inference_export", "horizons": {}}
    for horizon in HORIZONS:
        name = f"model_{horizon}h.joblib"
        source, target = original / name, staged / name
        audits = []
        with recover_portable_boosters(audits):
            artifact = joblib.load(source)
        if artifact.get("schema_version") != SCHEMA_VERSION or artifact.get("horizon_h") != horizon:
            raise ValueError("Bundle schema/horizon metadata does not match the consumer")
        order = artifact["feature_columns"]
        pipeline = artifact.get("feature_pipeline")
        expected = ENSEMBLE_FEATURES if pipeline == PIPELINE_VERSION else FEATURE_COLUMNS
        if pipeline not in (None, PIPELINE_VERSION) or len(order) != len(expected) or set(order) != set(expected):
            raise ValueError("Bundle predictors do not match a supported pipeline")
        joblib.dump(artifact, target)
        # Reload normally, without any monkeypatch, including calibration.
        reloaded = joblib.load(target)
        values = np.zeros((2, len(order)))
        before = artifact["primary_model"].predict_proba(values)
        after = reloaded["primary_model"].predict_proba(values)
        np.testing.assert_array_equal(before, after)
        if not np.isfinite(after).all() or ((after < 0) | (after > 1)).any():
            raise ValueError("Converted calibrated model produced invalid probabilities")
        entries[str(horizon)] = {"filename": name, "format": "joblib",
                                "model_version": artifact["model_version"],
                                "feature_order": order, "positive_class": 1,
                                **({"feature_pipeline": pipeline} if pipeline else {})}
        report["horizons"][str(horizon)] = {
            "original_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "converted_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            "boosters": audits, "calibrated_roundtrip_identical": True}
    # Preserve every supplied top-level field; entries reflect the real bundles.
    manifest["schema_version"] = SCHEMA_VERSION
    manifest["models"] = entries
    manifest["metadata_note"] = "Per-horizon models entries are authoritative. Original top-level model_version/feature_order are retained as supplied and differ from the actual bundles."
    (staged / manifest_path.name).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    load_artifact_manifest(staged)
    (backup_dir / "conversion_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    # Publish only after every staged bundle and the complete manifest validates.
    for horizon in HORIZONS:
        name = f"model_{horizon}h.joblib"
        temporary = model_dir / (name + ".tmp")
        shutil.copyfile(staged / name, temporary)
        temporary.replace(model_dir / name)
    temporary = manifest_path.with_suffix(".json.tmp")
    shutil.copyfile(staged / manifest_path.name, temporary)
    temporary.replace(manifest_path)
    print(f"Repaired schema {SCHEMA_VERSION}; converted {len(entries)} bundles. Backups/audit: {backup_dir}")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--backup-dir", type=Path, required=True)
    args = parser.parse_args()
    repair(args.model_dir, args.backup_dir)


if __name__ == "__main__":
    main()
