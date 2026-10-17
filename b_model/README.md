# Role B — ML lead

**Final hackathon handoff:** read [FINAL_HANDOFF.md](FINAL_HANDOFF.md) and use
`python -m b_model.predict --config-name replay_regional` for the main 40-cell
demo. Role B's implementation and retrospective evaluation are complete; the
model remains provisional for historical replay and human review. Operational
fire-alert readiness has not been established.

The interrupted recency/source-audit handoff has been verified locally; see
[RECENCY_RESULTS.md](RECENCY_RESULTS.md#independent-handoff-verification) and the
saved completion report. `python -m b_model.verify_recency_handoff` checks frozen
selection, re-scores the selected models/policies, verifies source hashes and
runs the actual inference CLI without promoting a candidate or writing shared
feeds. It requires a fresh output directory; use `--output-dir` for repeats.

## Recency, calibrated alert operating points, and source audit

[RECENCY_RESULTS.md](RECENCY_RESULTS.md) compares full history, recent 180/365-day
windows and 90/180-day decay weights across four dated periods. Probability
calibration and policy calibration are distinct, with a 72-hour internal purge.
Training-only decay/class balancing is applied once and normalized to mean one.
The separate research alert policy ranks up to five eligible cells per daily
00:00 UTC snapshot, then applies a threshold chosen only on policy-calibration
labels. Shared risk levels and C's dispatch policy stay unchanged.

```bash
OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 MKL_NUM_THREADS=2 \
  python -m b_model.recency_study
python -m b_model.recency_handoff
python -m b_model.predict --config-name replay_recency
```

Existing output/model directories are refused. Use fresh paths in a copy of
`conf/recency_study.yaml` for a repeated study; the review candidate is separate
from `CURRENT_HANDOFF.json`. Its calibration-only settings are in
`model_recency_candidate/operating_points.json`. Calibration-chosen filters can
send fewer actual alerts than the fixed-five reference; compare both counts
before claiming an improvement at equal workload.

[SOURCE_CONSISTENCY.md](SOURCE_CONSISTENCY.md) records the read-only audit and the
exact evidence request for Role A. The local files do not overlap in time and
original export filters were not saved. Source attribution remains unresolved;
class weighting does not repair unverified coverage. No new dependencies were
added for these studies.

## Current handoff: updated 40-cell regional scope

Use [REGIONAL_RESULTS.md](REGIONAL_RESULTS.md) and `conf/replay_regional.yaml`
for the new points across five provinces. The 33-cell reports below are
historical experiments; their numbers do not describe this new geography.

```bash
python -m b_model.predict --config-name replay_regional
python -m contracts.validate --kind risk b_model/experiment_results/20261017_regional_40/risk.json
python -m b_model.quality b_model/model_regional_40/metrics.json
```

The named profile binds A's matching `regional_40/features.json` and full history
to `b_model/model_regional_40/`, with risk in B's regional evidence directory.
`CURRENT_HANDOFF.json` lists the exact matching A/B paths and fingerprints for
C/D/E. Switch features, geometry, history and risk together. Shared
`data/processed/` still represents the separate legacy 33-cell replay and is
owned jointly by other roles; this B handoff does not mix the two scopes.

Reproduce the new comparison and packaging using fresh output paths:

```bash
OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 MKL_NUM_THREADS=2 \
  python -m b_model.backtest --config b_model/conf/backtest_regional.yaml
python -m b_model.regional_handoff
```

The backtest freezes the per-horizon backend choice from three development
periods before the final period is scored. It includes calibrated dryness
baselines, all/quiet subgroups and matched top-five budgets. Published regional
bundles retain the chosen preprocessing and empirical sigmoid calibration.

Software correctness and model acceptance are separate: `make model-test`
does not require all dry scenarios to become CRITICAL or invent a lead-time
hierarchy. The explicit `b_model.quality` command exits 1 for a model that fails
to beat its own saved AP baseline or has zero recall at its recorded cutoff.
This is only a minimal candidate gate, not operational certification.

Install `b_model/requirements-repair.txt` to run the optional trusted-artifact
repair test as well. It includes [py-ubjson](https://github.com/Iotic-Labs/py-ubjson)
(Apache-2.0), a conversion/test dependency rather than a normal inference
dependency. The incoming `b_model/model/` upload is preserved and its quality
rejection remains recorded; the regional profile selects separate artifacts.

## Uploaded XGBoost integration repair

The active `b_model/model/` upload has been integrated with the processed 33-cell
replay. Its actual bundles declare schema `1.0`, model version `v1`, and the 29
canonical-plus-leading-indicator predictors. The supplied top-level manifest
listed a different version and unrelated feature names. Those supplied fields
are retained, while authoritative `models` entries now match each real bundle.

The Linux-trained XGBoost 3.4.1 pickle also failed on Windows with
`input stream corrupted`, matching the RNG snapshot portability issue described
by [XGBoost maintainers](https://github.com/dmlc/xgboost/issues/12459).
`repair_artifacts.py` explicitly converts trusted snapshots through stable
Model IO, verifies equality of every stored model field, and retains the original
imputer, scaler, explanations and calibration. `portable_xgboost.PortableBooster`
persists the inference model in UBJSON without training RNG state; it is not a
checkpoint for exactly resuming stochastic training. Inference uses the normal
loader and performs no monkeypatching or error suppression.

Original uploads, previous processed feeds, and conversion checks are backed up
under `b_model/runs/uploaded_xgboost_integration_backup_02/`. Results and current
artifact/feed fingerprints are recorded in `b_model/model/integration_check.json`.
The run produced **99 LOW predictions, zero dispatch records and zero new
simulated notifications**. No probabilities or risk thresholds were adjusted.

```bash
# Reproduce inference using the installed/declared dependencies.
uv run --no-project --with-requirements b_model/requirements-training.txt python -m b_model.predict paths.features=data/processed/features.json paths.model_dir=b_model/model paths.output=data/processed/risk.json
python -m c_agent.agent --data-dir data/processed --output data/processed/dispatch.json --water-sources data/demo/role_a_real/water_sources.geojson
python -m contracts.validate --data-dir data/processed
```

Conversion-only library: [py-ubjson](https://github.com/Iotic-Labs/py-ubjson)
(Apache-2.0), used to decode complete UBJSON snapshots during explicit recovery.
It is not required for normal inference. Role E should add it to the root
dependency inventory if this repair tooling is distributed.

For another *new, trusted* upload, use a fresh backup path:

```bash
uv run --no-project --with-requirements b_model/requirements-training.txt --with py-ubjson python -m b_model.repair_artifacts --model-dir b_model/model --backup-dir b_model/runs/new_upload_backup
```

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
metadata per horizon. The first real XGBoost run is now evaluated in
[TEAMMATE_RESULTS.md](TEAMMATE_RESULTS.md): quiet-cell ranking/recall improved,
while overall AP and Brier worsened against the prior Logistic Regression
candidate on matched dates. This retrospective comparison is not a fresh unseen
test. Snap ML and IBM hardware acceleration remain untested. Evaluate on an
untouched period before replacing the published models.

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

The isolated forecast-horizon study tests 1/2/3/5/7/14 days with identical
27-feature Logistic Regression settings, common observed rows and full 14-day
purges for every horizon. See [HORIZON_RESULTS.md](HORIZON_RESULTS.md). Longer
horizons are research-only labels rebuilt from A's raw-event handoff; canonical
24/48/72-hour labels must match A exactly before fitting. No shared contract or
feed changes. `conf/horizon_study.yaml` fixes the protocol before evaluation.

```bash
OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 MKL_NUM_THREADS=2 \
  python -m b_model.horizon_study
# Optional figures; install requirements-analysis.txt for this command.
python -m b_model.plot_horizon_study
```

The runner refuses existing run/evidence directories. Use a copied config with
fresh output paths for a repeat. Plotting uses optional
[Matplotlib](https://matplotlib.org/) (Matplotlib license), recorded in
`requirements-analysis.txt`; it is not a model-serving dependency.

The paired rolling-origin and fixed-alert-budget comparison is documented in
[BACKTEST_RESULTS.md](BACKTEST_RESULTS.md). It retrains the prior Logistic
Regression configuration and the teammate's XGBoost configuration separately
before each of four evaluation periods. All settings are frozen in
`conf/backtest.yaml`; earlier periods/settings were already inspected, so these
are retrospective results. The primary budget is five cells per daily 00:00 UTC
snapshot per horizon, with hourly sensitivity results and a separate quiet-cell
pool. It does not change risk thresholds or Role C's dispatch policy.

```bash
OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 MKL_NUM_THREADS=2 \
  python -m b_model.backtest
```

The runner requires fresh run/evidence directories and refuses to replace an
existing evaluation. Models and per-row predictions stay in ignored `runs/`;
protocol, metrics, partition audits and per-day budget counts are saved in
`experiment_results/20261017_backtest/`. No shared feeds are written.

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
