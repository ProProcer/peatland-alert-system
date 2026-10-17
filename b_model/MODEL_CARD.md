# Model card — Peat Fire Early-Warning Model

The latest auto training path is a Snap ML/XGBoost ensemble with
two causal internal leading indicators and fivefold quiet-positive weighting.
It preserves temporal embargoes, separately fitted calibration and frozen risk
boundaries. A real XGBoost run now has a matched-date retrospective evaluation:
quiet-cell AP/recall improved, while overall AP and Brier worsened against the
prior Logistic Regression candidate. See [TEAMMATE_RESULTS.md](TEAMMATE_RESULTS.md).
Snap ML remains unevaluated; this run did not replace the shared model/feed.
The subsequent [rolling-origin and alert-budget check](BACKTEST_RESULTS.md)
found mixed earlier-period quiet-cell improvements and favored Logistic
Regression at a daily five-cell budget in the latest period. Higher recall at
cutoff 0.50 alone does not establish better performance at a fixed alert budget.
See `README.md` and `leading_indicators.py` for the exact feature/weight definitions
and history requirements. Original explicit legacy profiles remain available.

Role B, PIC 2 · JSON schema `1.0` · horizons `24`, `48`, `72` hours.

## Prediction target and intended use

For each 0.1° peat-intersecting cell, predict whether at least one nominal/high-confidence FIRMS surface hotspot appears during `(t, t + horizon_h]`. The target is future hotspot occurrence. Dryness is an engineered input to the baseline, not the target or a probability.

Outputs support simulated notifications and the command-center demo. FIRMS observes thermal surface anomalies; it does not directly observe underground peat smoldering. Predictions do not establish that a fire is certain or explain its cause.

## Training configuration and ownership

PIC 2 owns `train.py`, `training_config.py`, `conf/training.yaml`, the `model/`, `dryness/`, and `explanation/` config groups, and this card. PIC 1 owns parsing, its existing inference configuration and `predict.py`. See [PIC2_HANDOFF.md](PIC2_HANDOFF.md) for the shared artifact interface.

Activate the repository `.venv` and install `b_model/requirements-training.txt`. It includes the shared requirements, root artifact constraints and pandas below version 3 for PIC 1's current Arrow string alignment. Existing artifacts identify scikit-learn 1.6.1. Hydra Core 1.3.2 and OmegaConf 2.3.0 provide typed YAML composition and CLI overrides.

```bash
# Preview all training settings without fitting.
python -m b_model.train --cfg job

# Train from the supplied history; artifacts go to a separate timestamped run.
python -m b_model.train model=hist_gradient_boosting model.learning_rate=0.05

# Explicit alternative model and isolated output directory.
python -m b_model.train model=logistic_regression model.logistic_c=0.5 paths.model_dir=b_model/runs/logistic
```

Every successful run saves `training_config.yaml`, `metrics.json`, `artifact_manifest.json` and one joblib bundle per horizon. The manifest declares the filename, format, model version, feature order and positive class for each horizon. Metrics record the data file's SHA-256, used row count, split time ranges, selected backend and library versions. This identifies a run's inputs; it does not prove their provenance or label validity. Existing `b_model/model/` artifacts are not replaced by the default Hydra run.

## Inputs, labels and temporal validation

Configured training requires `history.parquet` with `cell_id`, UTC `ts` strings ending in `Z`, all 27 canonical numeric features, and producer-supplied `target_24h`, `target_48h`, `target_72h` labels. It rejects missing files, duplicate cell/timestamps, missing target columns and non-binary observed labels. Rows with incomplete future labels are excluded, not converted to negatives. A must construct labels from timestamped n/h-confidence events and document complete observation windows; trailing 24-hour hotspot counts alone do not establish new event times.

Default partitioning uses unique timestamps: first 55% for training, the next 20% for calibration, and the remaining 25% for final validation, before purging gaps. All cells at a timestamp stay together. Configured runs enforce the requested gap of at least 72 hours before calibration and validation. Short history fails rather than silently shortening the gap. Fractions describe boundaries before purging, so final row counts differ.

Median imputation and scaling are fit on training rows only. An entirely missing training feature is rejected because a median cannot be estimated. Gradient boosting's internal early stopping is disabled to avoid an automatic random holdout. Permutation importance uses calibration rows by default, or training rows when explicitly selected; the final validation slice is reserved for metrics.

For backward compatibility, the direct Python call `train_pipeline(...)` without a training config retains guarded calibration. All entry points require full 72-hour temporal gaps; short histories fail. The older target-generation helper remains available to direct callers; configured runs require A's labels instead. Prefer the Hydra entry point for experiments.

## Models and imbalance

A baseline Logistic Regression uses the dryness index plus the explicitly named features `peat_fraction`, `peat_area_km2`, `temp_c` and `precip_mm` by default. Its feature list, regularization and iteration limit are configurable.

The primary model uses all 27 original canonical predictors; Snap ML/XGBoost also use the two internal indicators described above. `model=auto` selects optional Snap ML when installed, otherwise XGBoost. Explicit choices are `hist_gradient_boosting`, `logistic_regression`, `xgboost`, and `snapml`; explicit Snap ML selection fails clearly when that optional dependency is absent. The logistic primary model includes its own fitted scaler so PIC 1 can continue supplying raw imputed predictors.

Legacy baseline/primary fits use `class_weight=balanced`. For Snap ML/XGBoost runs, baseline and primary instead use the custom training sample weights described in the README, without double balancing. Model iterations, learning rate, depth, regularization and seed are recorded in the resolved config. Configured calibration defaults to sigmoid fitting on the separate chronological calibration slice. Isotonic is an explicit alternative. Both require both target classes in that slice and never rescale probabilities to force CRITICAL alerts. `legacy_guarded` explicitly selects the old percentile/log-odds heuristic; its output should not be presented as empirically validated probability calibration.

## Engineered dryness index

The default rule is:

```text
rain = clip(days_since_rain / 30, 0, 1)
soil = clip(1 - sm_27_81 / 0.50, 0, 1)
air  = clip(vpd_mean_24h / 3.5, 0, 1)
dryness = 0.40 * rain + 0.40 * soil + 0.20 * air
```

Weights must be nonnegative and sum to one. Normalization references must be positive. These are hand-chosen project assumptions, not a validated standard peat-fire index. A dryness of 0.72 is not a 72% fire probability. At defaults, 21 rainless days, soil moisture 0.15 m³/m³ and VPD 2.8 kPa produce 0.72.

For the baseline feature only, missing rainless days default to 0, soil moisture to 0.30 m³/m³, and VPD to 1.5 kPa. Missing daily mean VPD first falls back to that row's current VPD. These explicit defaults are configurable and are distinct from the fitted median imputer used for the other model inputs. Neither path modifies source JSON or emits `-999`.

## Explanations and PIC 1 handoff

The implemented method is `signed_standardized`, a directional heuristic. Histogram boosting uses permutation importance; Snap ML uses its available feature importances; the logistic primary uses coefficient magnitudes. Configurable feature-priority multipliers and fixed domain signs turn these into `signed_feature_weights` saved in each artifact.

PIC 1 reads the saved weights and fitted scaler, computes exact standardized-value-times-weight contributions without clipping, and ranks them by absolute magnitude. Signs and magnitudes are preserved for every risk level; extra factors are not fabricated. These values are directional heuristics, not SHAP values, causal effects, additive probability contributions, or guaranteed faithful explanations of an individual tree prediction. Installing SHAP alone does not change that behavior.

`top_k=3` and null explanation clipping settings match PIC 1's current three-factor, unclipped consumer. Training validation rejects incompatible overrides. The separate `baseline.z_score_clip=3` setting applies only to the baseline's standardized inputs; it does not clip primary-model explanations. Training-side priority multipliers and importance settings affect the saved weights that inference consumes.

## Evaluation and evidence status

Average Precision (PR-AUC) is the primary metric and permutation-importance
scorer. Legacy explicit estimators use balanced class weights; the new auto
ensemble uses the custom sample weights described in the README. Each
horizon also records a diagnostic `optimal_threshold` maximizing validation F1
over its precision-recall curve. Ties use the highest threshold; single-class
validation records null. Threshold-tuned metrics reuse validation labels and
are optimistic, so an untouched future period is needed to establish performance.
The threshold is saved in the bundle and metrics without changing the artifact
manifest or inference risk boundaries. PR-AUC is saved at full precision.

New runs compute PR-AUC, ROC-AUC, precision, recall, F1 and baseline comparison on the untouched final validation slice. Classification metrics use a 0.50 decision cutoff; dispatch risk levels retain Contract 3.2 boundaries 0.35, 0.60 and 0.80. PR-AUC/ROC-AUC are null when the validation slice has only one class. Lead time is an approximate retrospective calculation from the available hotspot-count series; when no qualifying onset/alert pair is observed it is null. No minimum lead time, monotonic horizon ordering or superiority over the baseline is fabricated.

The pre-existing `b_model/model/` artifacts remain legacy demo artifacts. A first real run on Role A's 33-cell 2025 handoff is saved separately in `b_model/model_real_2025/`; [REAL_DATA_CHECK.md](REAL_DATA_CHECK.md) records its data fingerprint, dated split boundaries and results. All three primary models have zero validation recall at 0.50, and their PR-AUC is below the logistic/dryness baseline. The October 2026 replay yields 99 LOW risks and no simulated dispatch. This candidate demonstrates interface compatibility and must not be presented as an accepted operational model. The generic inference profile still selects the legacy model directory; the named `replay_role_a` profile selects the real candidate explicitly.

Earlier hardware timing claims are not retained as measured evidence. Real replay inference took 2.552 seconds in a fresh local process with native thread counts set to two; this does not establish LinuxONE performance. Synthetic acceptance tests demonstrate software behavior, not prediction quality. A documents source provenance and declares FIRMS export completeness; independent satellite observation availability has not been established.

A subsequent isolated chronological experiment selected regularized 27-feature Logistic Regression with sigmoid calibration for all horizons. On a separate September 22–October 13, 2026 evaluation, PR-AUC was 0.901/0.941/0.958 and recall at cutoff 0.50 was 0.787/0.873/0.888. Positive prevalence was 0.687/0.794/0.850; performance on quiet-hour records is substantially weaker. The earlier candidate was reevaluated on that same period for comparison. See [EXPERIMENT_RESULTS.md](EXPERIMENT_RESULTS.md) for the protocol, baselines, source audit, subgroup results and reproducible evidence. Portable selected bundles are tracked in `b_model/model_candidate_2026/` and selected by `--config-name replay_candidate`; the original run is under ignored `b_model/runs/chronological_experiment/`. Shared feeds and earlier published model directories remain unchanged.

## Deployment and scientific limits

Open-Meteo soil moisture is numerically modeled data, not physical sensor telemetry. In-situ readings could populate compatible weather fields, but units, depths, distributions and calibration would need validation before using the saved models. Schema compatibility does not establish model compatibility without retraining or evaluation.

The supplied peat format contains no depth attribute. Water sources are outside the model inputs. FIRMS event detection and coverage can miss fires; absence of a detected hotspot is not proof of absence of combustion. PIC 1 now preserves calibrated probabilities without rounding or clipping and reads verified model metadata from the artifact manifest.

LinuxONE/s390x dependency installation, optional Snap ML execution, resource use and latency must be measured with Role E on the target machine. This setup does not establish architecture support from a local x86 test. Optional Snap ML and SHAP are not required for the local configured training path.
