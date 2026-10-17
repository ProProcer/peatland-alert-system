# Role B — ML lead

## Early-warning ensemble training

`train.py` now defaults to Snap ML boosting when installed, otherwise XGBoost.
Explicit `model=snapml` fails when Snap ML is absent; `model=xgboost` selects the
fallback directly. Existing explicit Logistic Regression / histogram-boosting
profiles and saved 27-predictor models remain supported for comparisons.

```bash
python -m pip install -r b_model/requirements-training.txt
python -m b_model.train model=auto paths.model_dir=b_model/runs/early_warning
# For the real source bundle, use the extended history explicitly:
python -m b_model.train model=auto paths.history=data/demo/role_a_real/hackathon/history.parquet paths.model_dir=b_model/runs/early_warning_real
python -m b_model.predict paths.model_dir=b_model/runs/early_warning_real paths.features=data/demo/role_a_real/hackathon/features.json paths.history=data/demo/role_a_real/hackathon/history.parquet paths.output=b_model/.test-output/early_warning/risk.json
```

Snap ML/XGBoost fit with custom training-only sample weights, without additional
class balancing: negatives = 1; positives = training negatives / positives;
positives with observed zero `hotspots_in_cell_24h` multiply this by 5 by default.
Unknown recent-hotspot counts are not classified as quiet. Calibration and
validation keep the observed distribution. `model.cold_start_multiplier` and
`model.colsample_bytree` (default 0.7) are configurable. Column subsampling reduces
feature availability per tree; it cannot guarantee weather/soil splits.

Both tree backends add two internal predictors through `leading_indicators.py`:
`cumulative_dry_days` counts consecutive observed complete UTC days with daily
precipitation <1 mm; before 23:00, the current day is not yet counted. Missing
hours/rain make the day unknown and break the streak, so streaks can be lower
bounds at the beginning of history or after a gap. `soil_moisture_momentum` is
current `sm_27_81` minus the preceding 72-hour mean, excluding the current hour.
Incomplete soil context remains null and uses the fitted training median.
These are observed drying signals, not direct measures of ignition.

The extended artifact manifest declares 29 predictors and
`feature_pipeline: leading_indicators_v1`; training and inference share the same
causal transform. The inference path requires history, reads only four predictor
columns, and excludes measurements at/after each snapshot before inserting the
snapshot itself. Shared JSON schema 1.0 stays unchanged. `top_factors` continues
to summarize only the 27 canonical predictors; internal-indicator contributions
are omitted, making this an incomplete heuristic explanation, not SHAP.

Metrics retain chronological gaps of at least 72 hours, Average Precision,
diagnostic F1 thresholds, and now `quiet_case` precision/recall/AP and sample-weight
metadata per horizon. No recall improvement or IBM hardware acceleration has
been established by these code changes. Evaluate a new candidate on an untouched
period before replacing the published models. Existing candidate reports describe
earlier runs and do not evaluate this ensemble.

Added library: [XGBoost](https://xgboost.readthedocs.io/en/stable/) (Apache-2.0),
used for CPU histogram boosting fallback and loading its exported models.
Snap API reference: [BoostingMachineClassifier](https://snapml.readthedocs.io/en/latest/boosting_machines.html).
Role E should include XGBoost in the root dependency inventory and verify actual
Snap ML/XGBoost dependency installation, inference and timing on LinuxONE/s390x.
The local tests exercise XGBoost and a Snap-constructor stub; they do not prove
Snap ML runtime or architecture compatibility. No new dataset is introduced.

Read `TEAM_PLAYBOOK.md`, `contracts/CONTRACTS.md` and the existing `MODEL_CARD.md`. Own this folder and `data/processed/risk.json`. The repository setup preserves the pre-existing implementation, model artifacts and tests.

```bash
bash scripts/setup.sh b
source .venv/bin/activate
make mock
python -m b_model.predict --input data/demo/features.json --output data/demo/risk.json
python -m contracts.validate --kind risk data/demo/risk.json
make model-test
```

The mock pipeline replays `b_model/mock_output.json`, so it works without model dependencies. The inference command above instead loads the existing joblib artifacts and produces real model output on synthetic features. Use explicit output paths for experiments.

Root `constraints.txt` pins scikit-learn 1.6.1, as recorded in the existing artifacts. Install through the setup script or use that constraint file explicitly; the original role requirements contain only minimum versions.

`make model-test` runs the existing tests in a temporary copy: some regenerate default historical data, so running pytest directly in the shared workspace can overwrite A's training handoff.

Training is separate. PIC 2's Hydra entry point supports configuration preview and overrides:

```bash
python -m b_model.train --help
python -m b_model.train --cfg job
python -m b_model.train model=hist_gradient_boosting model.learning_rate=0.05
```

Coordinate with A on `target_24h`, `target_48h`, `target_72h`, n/h-confidence hotspot labels, hourly coverage and incomplete future windows. Use chronological validation with a purge gap; prevent future label leakage. Compare the logistic / dryness baseline with gradient boosting and measure precision, recall and lead time honestly. Verify the source and evaluation provenance of the existing historical data, model artifacts and reported metrics before using them as submission evidence.

Preserve 27 canonical input features and the fixed risk thresholds. Emit the latest timestamp per cell and all three horizons, along with top contributing factors. Existing `predict.py` has surge flags; write surged features to an isolated file to keep C's inputs consistent during a demo.

Coordinate optional IBM Snap ML and `s390x` dependency checks with E. Do not assume local wheels or latency claims establish LinuxONE compatibility. State clearly that soil data is modeled and FIRMS observes surface emergence; demonstrate how sensor readings map to the existing weather fields. Done when inference on A's real features completes within a minute and the risk contract validates.

## Hydra inference (PIC 1)

Install `b_model/requirements.txt` using the root constraints. The configuration is
`b_model/conf/config.yaml`, backed by dataclasses in `config.py`. For an isolated run:

```bash
python -m b_model.predict paths.features=a_data/mock_output.json paths.output=b_model/.test-output/risk.json
python -m contracts.validate --kind risk b_model/.test-output/risk.json
```

Paths resolve relative to the repository root, including when called from another
directory. Override them with Hydra arguments or environment variables
`PEAT_FEATURES`, `PEAT_HISTORY`, `PEAT_MODELS`, and `PEAT_RISK`. Windows Hydra overrides
should use forward slashes and quote the whole argument when it contains spaces.
The configured output basename must be `risk.json`. The existing argparse
`--input` / `--output` command and surge flags remain supported; use one CLI style
per invocation. Both CLI styles compose the same YAML and environment defaults,
then use the same validation and execution functions. Hydra logging creates no
files and does not change directories. Legacy `--history` overrides `paths.history`.

`paths.history` reads only Parquet schema metadata to align predictor column order
and dtypes. Targets (`target_24h`, `target_48h`, `target_72h`) are excluded because
future outcomes are unavailable at inference time. Metadata absent from history,
such as `schema_version`, remains validated at input rather than fabricated as a
historical column. Missing integer measurements use pandas nullable integer dtypes
until imputation; this is the necessary representation difference from non-nullable
historical integer columns. Set `paths.history=null` explicitly to use the canonical
predictor schema without a historical reference.

Continuous nulls use each saved model's fitted median imputer. Hotspot counts also
use artifact medians by default, preserving the existing training preprocessing;
`imputation.hotspot_counts=zero` explicitly enables zero filling for the two count
columns. Zero filling is a changed missing-data assumption and should be evaluated
before operational use. Neither setting modifies the source JSON or emits sentinels.
Missing input, duplicate records/keys, malformed timestamps, coordinate mismatches,
nonfinite values, and `-999` measurements fail explicitly instead of creating mocks.
Required keys and nested object types are checked before access. Unexpected keys
are rejected; missing measurements must be explicit nulls. Errors identify the
zero-based record index and field path. Integer casts check signed/unsigned bounds,
preserve nullable unsigned types, and reject fractional values or overflow.

Output is the frozen Contract 3.2 array with all three horizons and each cell's
latest timestamp, validated before atomic replacement. `summarize_predictions`
provides an internal `scores` / `levels` / `top_factors` mapping without changing
the handoff. The calibrated model probability is saved without rounding or clipping,
and the fixed risk thresholds are applied to that same value. Display rounding
belongs in the frontend. Contributions are exact signed weights multiplied by
standardized feature values, ranked by absolute magnitude without sign filtering,
clipping, or fabricated fallbacks. These remain heuristic directional factors,
not SHAP values or a causal explanation. Saved model bundles are unchanged.

Inference never overwrites the source features or history, including during a
failed run. A synthetic demo feed requires an explicit separate path:

```bash
python -m b_model.predict paths.features=a_data/mock_output.json paths.output=b_model/.test-output/risk.json surge_cell=-2.35_114.05 paths.demo_features_out=b_model/.test-output/surged_features.json
```

Unknown surge cells and input/output collisions are rejected. The legacy
`--write-surged-features` flag requires `--surge-output-features`; there is no
fallback to modifying the input. The demo feed uses the same transformation as
inference. Each output is replaced atomically; the two files are not a single
filesystem transaction. Serialization or replacement failures preserve that
destination's previous complete file and remove temporary files.

## PIC 2 artifact manifest

The model directory must include `artifact_manifest.json`, with schema version
`1.0` and a `models` object containing exactly `24`, `48`, and `72` entries. The
checked-in manifest describes the existing unmodified bundles. Each entry has:

```json
{
  "filename": "model_24h.joblib",
  "format": "joblib",
  "model_version": "v1",
  "feature_order": ["peat_fraction", "peat_area_km2", "...all 27 canonical features..."],
  "positive_class": 1
}
```

The abbreviated feature list above is illustrative; copy the complete checked-in
manifest when exporting a compatible bundle. `format` is `joblib` or `pickle`;
filenames can be customized, including `.pkl`. Paths must remain inside the model
directory. Each feature occurs exactly once; inference reorders the predictor
projection to that order. Artifact metadata must agree with the manifest, and the
output `model_version` comes from the verified entry. Probability column selection
uses the model's binary `classes_`, allowing reversed class order.

Bundles contain `horizon_h`, `schema_version`, `model_version`, `feature_columns`,
a fitted median `imputer`, fitted `scaler`, `primary_model` (or `model`), and
`signed_feature_weights` (or `feature_weights`) in the declared order. PIC 2's
`train.py` now publishes this manifest after exporting all three bundles. Only
load trusted training artifacts: both pickle and Joblib execute
deserialization code, and a manifest is not a security sandbox.

`max_seconds` defaults to 60 and rejects an over-budget result before publishing.
It is a latency check, not a hard cancellation mechanism for native model code.
The acceptance suite measures a fresh CLI process on 300 synthetic cells; this
does not establish performance on A's real data or IBM LinuxONE hardware.

Dependency attribution for Role E's root README inventory:

| Added library | Purpose | Source |
| --- | --- | --- |
| Hydra Core 1.3.2 | YAML configuration, composition and CLI overrides | https://hydra.cc/docs/1.3/intro/ |
| OmegaConf 2.3.0 | Structured configuration validation and environment interpolation | https://omegaconf.readthedocs.io/en/2.3_branch/structured_config.html |

No new datasets are introduced. Root README changes remain with Role E.

## Hydra training (PIC 2)

Activate `.venv` and install the declared dependencies:

```bash
source .venv/bin/activate
python -m pip install -r b_model/requirements-training.txt
python -m pip check
```

Training configuration lives in `conf/training.yaml`, backed by typed schemas in
`training_config.py`. It is independent of PIC 1's `conf/config.yaml`. Its config
groups select the main model, engineered dryness feature and explanation settings:

```text
conf/training.yaml        Paths, split fractions, embargo, seed, baseline, calibration
conf/model/              auto, hist_gradient_boosting, logistic_regression, snapml
conf/dryness/default.yaml Weights, normalizing references, explicit missing-value defaults
conf/explanation/default.yaml Importance settings and feature-priority multipliers
```

`requirements-training.txt` includes the shared role requirements, the root
scikit-learn artifact constraint, and `pandas<3`. That pandas bound keeps the
current PIC 1 Arrow/schema alignment compatible with historical string dtypes;
coordinate lifting it with PIC 1. No change to PIC 1's requirement file is needed.

```bash
# Preview without fitting or creating artifacts.
python -m b_model.train --cfg job

# Run a repeatable experiment without replacing existing model artifacts.
python -m b_model.train model=hist_gradient_boosting model.max_depth=3 seed=7

# Choose a different primary model; its scaler is fitted inside the saved model.
python -m b_model.train model=logistic_regression model.logistic_c=0.5

# Override dryness weights together so they still sum to one.
python -m b_model.train dryness.rain_weight=0.3 dryness.soil_weight=0.5 dryness.air_weight=0.2
```

Default Hydra output is a timestamped directory under ignored `b_model/runs/`.
Override `paths.history` and `paths.model_dir` when needed; relative paths resolve
from the repository root. Every successful run saves three compatible model
bundles, `metrics.json` and the resolved `training_config.yaml`. Data fingerprint,
split ranges, backend and library versions are saved for reproducibility. Unknown
keys, invalid types, incompatible settings and nonfinite values fail explicitly.

Configured runs require all producer-supplied future target columns and never
silently generate synthetic history. They enforce at least 72 hours between the
training/calibration and calibration/validation slices. Supply enough history for
nonempty splits with both classes in training and calibration. Short history fails
instead of reducing the gap. The older argparse `--input` / `--output` style is
retained; do not mix it with Hydra overrides. `--force-mock` is an explicit testing
option, not a substitute for A's labeled historical dataset.

Sigmoid calibration is the configured default; it does not force high-risk scores
to reach a demo threshold. The legacy direct Python API keeps its old guarded
calibration, but all entry points now require the full temporal embargo. New
metrics retain measured lead times, including null when unobserved, without forcing
a minimum or an increasing sequence across horizons.

Average Precision (PR-AUC) is the primary metric and the permutation-importance
scorer. Legacy explicit estimators use balanced class weights; the new ensemble
uses the custom sample weights described above, without double weighting.
Each horizon logs and saves `optimal_threshold`, chosen by maximum F1 over the
validation precision-recall curve (ties choose the highest threshold). The bundle
also stores this value; its manifest and inference interface remain unchanged.
`validation_tuned_metrics` describes the selected operating point and is optimistic
because it uses the same validation labels for selection and scoring. Evaluate a
frozen threshold on a later untouched period before claiming improvement.
Existing precision/recall/F1 remain at cutoff 0.50, and risk boundaries remain
0.35/0.60/0.80. The diagnostic threshold does not alter inference probabilities.
Single-class validation records a null optimal threshold. PR-AUC retains full
precision to avoid rounding rare-event differences away.

Parquet native datetime columns are accepted and normalized to UTC; naive native
datetime values are interpreted as UTC. String timestamps must still end in `Z`.
The default split remains 55% training / 20% calibration / 25% validation, before
purging 72-hour gaps. To reserve the latest 20% for validation, use
`split.train_ratio=0.60 split.calibration_ratio=0.20`; calibration remains separate
from fitting and final evaluation. Short data fails instead of shrinking gaps.

Read [PIC2_HANDOFF.md](PIC2_HANDOFF.md) before changing settings that inference also
uses. Dryness currently affects the baseline only. Explanation priorities affect
the saved weights that PIC 1 already consumes; changing the factor count or clipping
bounds requires a consumer update, so incompatible overrides are rejected today.

Run PIC 2 checks with `python -m pytest b_model/tests/test_training_config.py -q`.
Run the complete existing/new suite through `make model-test`, which preserves the
shared data by executing in a temporary copy. See [MODEL_CARD.md](MODEL_CARD.md) for
the precise target, validation protocol, heuristic explanation limits and evidence
status. These configurations follow Hydra's [structured-schema](https://hydra.cc/docs/1.3/tutorials/structured_config/schema/)
and [CLI override](https://hydra.cc/docs/1.3/advanced/override_grammar/basic/) mechanisms.

## Role A real-data replay

Role A's source handoff is in `data/demo/role_a_real/hackathon/`. With the human's
approval, its real replay has been published to `data/processed/`, together with
risk from the first real training run. `b_model/model/` retains the legacy demo
artifacts; `b_model/model_real_2025/` contains the explicitly selected real candidate.
See [A's handoff](../a_data/REAL_HANDOFF.md). The named training preset selects the
33-cell 2025 history and sklearn gradient boosting explicitly, preserving the
chronological splits, 72-hour embargoes, balanced class weights and sigmoid
calibration. Its default model directory is a separate timestamped run.

```bash
# Confirm the preset before training; actual Parquet files require Git LFS checkout.
python -m b_model.train --config-name training_role_a --cfg job
python -m b_model.train --config-name training_role_a paths.model_dir=b_model/runs/role_a_2025

# Use matching real features, history schema and newly trained artifacts together.
python -m b_model.predict paths.features=data/demo/role_a_real/hackathon/features.json paths.history=data/demo/role_a_real/hackathon/history_2025.parquet paths.model_dir=b_model/runs/role_a_2025 paths.output=b_model/.test-output/role_a_replay/risk.json
python -m contracts.validate --kind risk b_model/.test-output/role_a_replay/risk.json

# Reproduce the published real risk using the saved real candidate and processed inputs.
python -m b_model.predict --config-name replay_role_a
```

This is a historical replay at `2026-10-16T00:00:00Z`, producing 99 risk records
(33 cells times three horizons). To use the extended history, explicitly override
`paths.history=data/demo/role_a_real/hackathon/history.parquet` at training and
inference. Its incomplete future labels are excluded by configured training.
Never treat the replay as current-hour observations. E owns selecting and publishing
matching A/B/C/D feeds for integration.

Read [REAL_DATA_CHECK.md](REAL_DATA_CHECK.md) for the measured compatibility result
and the candidate's poor validation performance. A successful schema/latency check
does not establish useful prediction quality. The current live platform script
still calls A without `--replay` and therefore stops; use A's explicit replay export
and the named B replay configuration until E adds replay orchestration.

## Chronological experiments (PIC 2)

The completed real-data comparison is documented in
[EXPERIMENT_RESULTS.md](EXPERIMENT_RESULTS.md), with reviewable protocol and
metrics in `experiment_results/20261017/`.

Portable selected artifacts are tracked in `model_candidate_2026/`, together
with their manifest and provenance. Run the opt-in profile after pulling:

```bash
python -m b_model.predict --config-name replay_candidate
python -m contracts.validate --kind risk b_model/experiment_results/20261017/risk.json
```

That profile writes the separate candidate replay, preserving shared feeds.

`experiment.py` compares three regularized 27-feature Logistic Regressions and
three simpler boosting settings, each with sigmoid/isotonic calibration. The
logistic/dryness baseline is calibrated under the same protocol. It uses the
existing training dependencies; no new package or source data is required.

```bash
OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 MKL_NUM_THREADS=2 python -m b_model.experiment
# Use a fresh directory for another explicitly planned experiment.
python -m b_model.experiment --output-dir b_model/runs/another_experiment
```

The fixed boundaries and candidates are in `conf/experiment.yaml`. Three
development evaluations cover archive data and the archive-to-NRT transition.
All development evaluations finish before the final model's training cutoff;
separate final calibration and evaluation follow, with 72-hour embargoes.
Candidates are selected per horizon by mean calibrated development PR-AUC
(average precision), then Brier score. The selection is saved before any final
prediction metrics are calculated. Aggregate source/label counts had already
been inspected, so this is a retrospective temporal evaluation.

The output directory contains the protocol, input fingerprint, source audit,
partition dates/counts, full development results, frozen selection, final results,
consumer-compatible model bundles and an isolated `risk.json`. Evaluation also
compares the earlier published candidate, a past-hotspot persistence rule, and
the subgroup with no hotspots in the preceding 24 hours. High performance on
ongoing hotspots alone does not establish useful early warning.

Existing output directories are rejected to discourage repeated tuning against
the final period. Experiment outputs stay under ignored `b_model/runs/`; they
do not replace shared feeds or deployed artifacts. To test a completed candidate:

```bash
python -m b_model.predict --config-name replay_role_a paths.model_dir=b_model/runs/chronological_experiment/model paths.output=b_model/.test-output/experiment/risk.json
python -m contracts.validate --kind risk b_model/.test-output/experiment/risk.json
```
