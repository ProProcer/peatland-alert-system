# PIC 2 → PIC 1: training and inference agreement

## Leading-indicator ensemble extension

The latest `train.py` auto backend selects Snap ML or XGBoost, with custom
training-only cold-start sample weights. Its internal manifest includes all 27
canonical inputs plus `cumulative_dry_days` and `soil_moisture_momentum`, and the
explicit marker `feature_pipeline: leading_indicators_v1`. `predict.py` now
supports this extension as well as the original 27-input artifacts. Both paths
use `leading_indicators.py`; rolling inference requires `paths.history`, filters
future rows per cell, and never reads labels. See the new README section for
precise UTC-day, missingness and 72-hour lookback definitions.

This extends internal model inputs only. Shared features/risk schema 1.0 and risk
boundaries are unchanged. Engineered predictors are omitted from the canonical
`top_factors` summary, which remains an incomplete directional heuristic. The
earlier candidate described below has not been retrained or promoted by this
change. Legacy explicit training profiles still export 27 predictors.

## Improved candidate available for replay integration

The completed chronological experiment selected balanced Logistic Regression
with sigmoid calibration for all horizons. Portable artifacts and their manifest
are in `b_model/model_candidate_2026/`; the opt-in profile is `replay_candidate`.
Run `python -m b_model.predict --config-name replay_candidate` to write matching
candidate risk to `b_model/experiment_results/20261017/risk.json` (33 cells,
`2026-10-16T00:00:00Z`, three horizons). All 27 canonical predictors and schema 1.0
are preserved. This uses the actual existing PIC 1 consumer.

See [EXPERIMENT_RESULTS.md](EXPERIMENT_RESULTS.md) for the frozen development
selection, separate final evaluation, prior-model/baseline comparisons and source
audit. Overall performance improved, but 24-hour quiet-case recall is about 30%
at cutoff 0.50. This is a historical replay candidate; overall metrics include
ongoing hotspots and a high-prevalence final period.

E/C should select this model directory explicitly for the next isolated
integration run, retain A's matching features/geometry, and regenerate simulated
dispatch from the new candidate risk. Existing published risk/dispatch remain
the earlier run. The generic inference and `replay_role_a` profiles retain their
previous model selections. No C or E implementation was edited.

## Existing training and inference agreement

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

New internal metadata keys are `training_config`, `dryness_config`, `baseline_feature_columns`, `baseline_config`, `explanation_config` and `training_data`. Training also exports `artifact_manifest.json` declaring all three bundles and their feature order, model version, format and positive class. These do not add fields to `risk.json`.

Training-side feature priorities and permutation settings are configurable and feed the saved signed weights immediately. The output method remains a directional standardized heuristic, not SHAP. PIC 1 now ranks exact, unclipped signed standardized contributions by absolute magnitude and preserves both positive and negative factors without fabricating fallback values.

The current consumer emits three factors without clipping, so training validation requires `top_k=3` and null explanation clipping settings. The baseline has its own configurable `baseline.z_score_clip`, saved in `baseline_config`; that applies only when reconstructing baseline inputs. To make explanation factor count or clipping tunable later, PIC 1 must read the artifact's `explanation_config` and agree on that behavior. No consumer change is required for the current settings.

## Run a trained artifact

After PIC 2 shares a verified run directory, PIC 1 can select it using the existing interface:

```bash
python -m b_model.predict paths.model_dir=b_model/runs/<run-directory> paths.output=b_model/.test-output/risk.json
```

Keep `schema_version`, horizon values, UTC timestamps, canonical factor names and risk thresholds unchanged. Check the run's saved library versions before loading its joblib bundles on another machine. Local synthetic integration tests are not evidence of real-data quality or LinuxONE latency.
