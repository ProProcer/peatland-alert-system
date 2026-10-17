# Role B — ML lead

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
per invocation. Hydra logging creates no files and does not change directories.

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

Output is the frozen Contract 3.2 array with all three horizons and each cell's
latest timestamp, validated before atomic replacement. `summarize_predictions`
provides an internal `scores` / `levels` / `top_factors` mapping without changing
the handoff. Existing artifact probability clipping and heuristic directional
attributions are preserved; those factors are not SHAP values or a causal explanation.

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
calibration and short synthetic split behavior for backward compatibility. New
metrics retain measured lead times, including null when unobserved, without forcing
a minimum or an increasing sequence across horizons.

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
