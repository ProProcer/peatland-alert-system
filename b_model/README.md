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

Training is separate:

```bash
python -m b_model.train --help
python -m b_model.train --input data/processed/history.parquet --model-dir /tmp/peatland-model
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
