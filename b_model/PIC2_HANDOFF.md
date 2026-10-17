# PIC 2 → PIC 1: training and inference agreement

This is a handoff note for the teammate; no external message has been sent. Training changes stay in PIC 2 files. PIC 1's `config.py`, `features.py`, `predict.py`, `conf/config.yaml` and `tests/test_contract.py` remain unchanged by this work.

Install `requirements-training.txt` for the shared tested environment. It retains
scikit-learn 1.6.1 and bounds pandas below 3: the current Arrow string aligner
produces object columns while pandas 3 reads historical strings as its new string
dtype. PIC 1 should review that alignment before the team lifts the pandas bound.

## Dryness

The index is an engineered input to the baseline Logistic Regression. The primary model continues to use the original 27 predictors, so live primary inference does not need to recompute the index.

PIC 2's training helper reads `conf/dryness/default.yaml`, validates the weights/references and saves `dryness_config` in each joblib artifact. On complete data, defaults reproduce the current formula in PIC 1's `features.py`. The training helper also fills missing mean VPD from the same row's instantaneous VPD before using its configured default.

If PIC 1 later exposes baseline inference or a UI dryness display, it must use the artifact's saved `dryness_config` and `baseline_feature_columns`, with the fitted imputer/scaler. Reading today's YAML or calling the old fixed formula could disagree with the configuration used to train that baseline.

## Explanations

Existing artifact keys and model input ordering are retained:

- `feature_columns`: the canonical 27 names in their frozen order.
- `imputer`, `scaler`, `primary_model`: fitted state from training.
- `signed_feature_weights`: saved per-horizon weights that existing inference already uses.
- `feature_weights`, `model`: compatibility aliases retained for existing consumers.

New internal metadata keys are `training_config`, `dryness_config`, `baseline_feature_columns`, `explanation_config` and `training_data`. These do not add fields to `risk.json`.

Training-side feature priorities and permutation settings are configurable and feed the saved signed weights immediately. The output method remains a directional standardized heuristic, not SHAP. PIC 1's current positive/negative selection and fallback factors are documented in the model card.

The current consumer hard-codes three factors and clipping bounds. Training validation therefore rejects incompatible `top_k`, `z_score_clip` and `contribution_clip` overrides. To make those tunable later, PIC 1 must read `artifact['explanation_config']` and apply the corresponding values in its preprocessing/attribution calls, while retaining compatibility defaults for older artifacts. No such consumer change is required to use the new artifacts with the current settings.

## Run a trained artifact

After PIC 2 shares a verified run directory, PIC 1 can select it using the existing interface:

```bash
python -m b_model.predict paths.model_dir=b_model/runs/<run-directory> paths.output=b_model/.test-output/risk.json
```

Keep `schema_version`, horizon values, UTC timestamps, canonical factor names and risk thresholds unchanged. Check the run's saved library versions before loading its joblib bundles on another machine. Local synthetic integration tests are not evidence of real-data quality or LinuxONE latency.
