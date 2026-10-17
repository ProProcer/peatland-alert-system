# Teammate XGBoost evaluation — 2026-10-17

Teammate commit `489c4f4` added the Snap ML/XGBoost training path, two causal
drying predictors and fivefold weighting for positive training windows without
recent hotspots. No trained artifacts for that implementation were found locally.
All three XGBoost models have now been trained successfully. The prior Logistic
Regression candidate remains preferable for overall ranking and probability error
on this comparison; the new model improves quiet-cell ranking and recall.
Neither candidate was promoted to the shared feed by this run.

The subsequent [rolling-origin and fixed-budget comparison](BACKTEST_RESULTS.md)
found mixed earlier-period quiet-cell improvements. At five daily alerts in the
latest quiet-cell pool, Logistic Regression caught more positive windows. The
cutoff-based recall gain below should not be presented as a fixed-budget gain.

This is a retrospective benchmark on a previously inspected period, **not a fresh
unseen test**. Parameters were the teammate's defaults, fixed before these scores:
150 trees, depth 4, learning rate 0.05, L2 2, column sampling 0.7, quiet-positive
multiplier 5, seed 42, separate sigmoid calibration. No tuning followed evaluation.
The comparison combines model, feature and weighting changes; it cannot identify
which change caused a difference. Snap ML was unavailable and was not evaluated.

Training used Role A's extended real 33-cell history: 541,728 source rows,
539,352 with all three observed labels; 2,376 incomplete-label rows excluded.
Source SHA-256: `444152463a2aa952a6154c965d7c3876e48e4ffea1c86370ca811dafa76bfb40`.
The split dates and counts exactly match the previous candidate's final benchmark:

| Partition | First UTC hour | Last UTC hour | Rows |
| --- | --- | --- | ---: |
| Train | 2024-12-02T00:00:00Z | 2026-08-31T23:00:00Z | 505,296 |
| Calibration | 2026-09-04T00:00:00Z | 2026-09-18T23:00:00Z | 11,880 |
| Validation | 2026-09-22T00:00:00Z | 2026-10-13T23:00:00Z | 17,424 |

Both gaps are at least 72 hours. Imputation is fitted on training only; internal
indicators use measurements at or before each timestamp. The 29 predictors stay
internal to Role B; shared feature names and JSON schema 1.0 are unchanged.

| Horizon | Overall AP: prior LR | Overall AP: XGBoost | Overall Brier: prior LR | Overall Brier: XGBoost |
| --- | ---: | ---: | ---: | ---: |
| 24 h | 0.901 | 0.794 | 0.164 | 0.230 |
| 48 h | 0.941 | 0.891 | 0.133 | 0.186 |
| 72 h | 0.958 | 0.923 | 0.108 | 0.167 |

AP is Average Precision (higher is better); Brier is squared probability error
(lower is better). Positive prevalence is 0.687 / 0.794 / 0.850, so high aggregate
AP does not establish strong early-warning performance.

The same 5,545 validation windows have zero hotspots in the preceding 24 hours:

| Horizon | Quiet AP: prior LR | Quiet AP: XGBoost | Quiet recall at 0.50: prior LR | Quiet recall at 0.50: XGBoost | Quiet precision at 0.50: prior LR / XGBoost |
| --- | ---: | ---: | ---: | ---: | ---: |
| 24 h | 0.417 | 0.442 | 0.297 | 0.607 | 0.414 / 0.414 |
| 48 h | 0.605 | 0.662 | 0.499 | 0.676 | 0.630 / 0.630 |
| 72 h | 0.724 | 0.767 | 0.567 | 0.760 | 0.733 / 0.737 |

At 24 hours, quiet-cell recall approximately doubles, but most alerts at that
cutoff are still false positives. Quiet Brier improves at 24/72 hours and worsens
at 48 hours; full reliability bins and threshold diagnostics are in the evidence.
Hourly windows overlap and are not independent ignition events. Source coverage
and the archive/NRT transition remain unresolved in the earlier source audit.
Further dated evaluation is needed before changing the chosen model.

Inference on the real October 16 replay produced 99 predictions for 33 cells in
4.17 seconds in a fresh local CPU process with two OMP/BLAS threads. Contract
validation passed; `make model-test` passed all 122 tests. This is not an IBM
LinuxONE timing result. `top_factors` remains a heuristic over the canonical 27
features and omits the two internal indicators; it is an incomplete explanation.

Artifacts are local and ignored by Git in
`b_model/runs/teammate_xgboost_20261017/` (three joblib models, manifest,
resolved config and metrics). The environment has `xgboost-cpu==3.4.1`, imported
as `xgboost`. The metadata records its version and artifact hashes. Shared feeds
and previous model artifacts were preserved.

Reproduce training and replay from the repository root after installing training
dependencies. These commands replace this local comparison run's outputs:

```bash
OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 MKL_NUM_THREADS=2 \
  .venv/bin/python -m b_model.train --config-name training_teammate
OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 MKL_NUM_THREADS=2 \
  .venv/bin/python -m b_model.predict --config-name replay_teammate
```

The training ratios pin these dates only for the recorded source data; inspect
split ranges before using refreshed history. Machine-readable evidence is in
[experiment_results/20261017_teammate/](experiment_results/20261017_teammate/),
including `comparison.json`, `metrics.json`, `training_config.yaml`,
`artifact_manifest.json`, `metadata.json`, `inference_check.json` and `risk.json`.
