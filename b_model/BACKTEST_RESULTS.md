# Rolling-origin and fixed-budget evaluation — 2026-10-17

Logistic Regression remains the preferred overall demo candidate. XGBoost has mixed quiet-cell improvements across earlier periods, and its higher latest-period recall at cutoff 0.50 does not establish better ranking with a fixed alert budget. No model or shared feed was promoted.

## Protocol and limits

Both approaches were retrained before each of four periods, for all three horizons: 24 fits total. Training, calibration and evaluation are strictly chronological with at least 72-hour gaps. Training-only medians and separately fitted sigmoid calibration are used. Models never fit the evaluation rows; later periods can train on observations that were evaluation data in an earlier fold, as in a rolling-origin simulation.

This is retrospective: periods and the Logistic Regression settings were previously inspected. It is not an untouched external test or an unbiased model-selection estimate. LR uses C=0.001 / 0.001 / 0.1 for 24/48/72 hours; XGBoost uses the teammate defaults (150 trees, depth 4, learning rate 0.05, L2 2, column sampling 0.7, quiet-positive multiplier 5, seed 42). These settings were frozen before scoring, with no tuning afterward. XGBoost combines extra features and weighting as well as a different estimator, so changes cannot be attributed to architecture alone. Snap ML was not tested.

Source: Role A extended real 33-cell history, SHA-256 `444152463a2aa952a6154c965d7c3876e48e4ffea1c86370ca811dafa76bfb40`. All 539,352 common complete-label rows are eligible; 2,376 incomplete-label rows are excluded. Causal internal indicators are computed before label filtering. Predictor ordering is canonical timestamp/cell order.

| Period | Train ends before (UTC) | Calibration [start, end), UTC | Evaluation [start, end), UTC |
| --- | --- | --- | --- |
| archive_2025 | 2025-06-28T00:00:00Z | 2025-07-01T00:00:00Z → 2025-08-01T00:00:00Z | 2025-08-04T00:00:00Z → 2025-11-01T00:00:00Z |
| archive_2026 | 2025-12-29T00:00:00Z | 2026-01-01T00:00:00Z → 2026-04-01T00:00:00Z | 2026-04-04T00:00:00Z → 2026-07-01T00:00:00Z |
| nrt_transition | 2026-06-28T00:00:00Z | 2026-07-01T00:00:00Z → 2026-08-01T00:00:00Z | 2026-08-04T00:00:00Z → 2026-09-01T00:00:00Z |
| final_2026 | 2026-09-01T00:00:00Z | 2026-09-04T00:00:00Z → 2026-09-19T00:00:00Z | 2026-09-22T00:00:00Z → 2026-10-14T00:00:00Z |

## Ranking across periods

AP means Average Precision, with higher better; it is prevalence-dependent. Overall probability error (Brier, lower better), fixed-cutoff diagnostics and reliability bins are retained in `results.json`. Quiet means an observed zero count in the preceding 24 hours, not a confirmed new ignition. Unknown counts are excluded.

| Period | Horizon | Positive rate | Overall AP LR / XGB | Quiet positive windows | Quiet AP LR / XGB |
| --- | ---: | ---: | ---: | ---: | ---: |
| archive_2025 | 24 h | 0.0014 | 0.0021 / 0.0080 | 96 | 0.0022 / 0.0083 |
| archive_2025 | 48 h | 0.0027 | 0.0041 / 0.0058 | 192 | 0.0041 / 0.0059 |
| archive_2025 | 72 h | 0.0041 | 0.0062 / 0.0058 | 288 | 0.0062 / 0.0058 |
| archive_2026 | 24 h | 0.0038 | 0.0220 / 0.0082 | 263 | 0.0228 / 0.0083 |
| archive_2026 | 48 h | 0.0076 | 0.0294 / 0.0210 | 479 | 0.0232 / 0.0211 |
| archive_2026 | 72 h | 0.0109 | 0.0326 / 0.0291 | 712 | 0.0256 / 0.0292 |
| nrt_transition | 24 h | 0.2427 | 0.5175 / 0.4406 | 1754 | 0.1811 / 0.1973 |
| nrt_transition | 48 h | 0.3202 | 0.6787 / 0.5547 | 2916 | 0.3801 / 0.3277 |
| nrt_transition | 72 h | 0.3739 | 0.7364 / 0.6742 | 3749 | 0.4591 / 0.4536 |
| final_2026 | 24 h | 0.6870 | 0.9008 / 0.7936 | 1868 | 0.4167 / 0.4415 |
| final_2026 | 48 h | 0.7942 | 0.9406 / 0.8928 | 2819 | 0.6049 / 0.6651 |
| final_2026 | 72 h | 0.8499 | 0.9577 / 0.9373 | 3336 | 0.7236 / 0.7947 |

XGBoost improves quiet-cell AP in 4/9 earlier period/horizon comparisons. This is not a consistent win. Scores in sparse archive periods are low for both models; a handful of detections generates many overlapping hourly positive windows.

## Five alerts per snapshot

Primary snapshots are daily at 00:00 UTC. Each model independently ranks cells and selects five per horizon, without a probability cutoff. This is a budget experiment, not the frozen risk-level or Role C dispatch policy. It forces five selections even when every probability is low. Ties are broken by cell_id ascending, without labels; tie counts are saved. Quiet-only ranking is a separate hypothetical allocation of up to five alerts among eligible quiet cells. If fewer than five are eligible, all are selected. Empty eligible pools have no alerts. Both models have exactly matching alert counts, eligible pools and labels in every comparison.

Each hit is one selected cell whose future window contains a hotspot; it is not a unique fire, dispatch or avoided incident. Misses are positive windows outside the selected list. Daily sampling reduces repeated snapshots but does not make overlapping 48/72-hour targets independent.

| Period | Horizon | All-cell alerts each | All-cell hits LR / XGB | Quiet-only alerts each | Quiet-only hits LR / XGB |
| --- | ---: | ---: | ---: | ---: | ---: |
| archive_2025 | 24 h | 445 | 1 / 1 | 445 | 1 / 1 |
| archive_2025 | 48 h | 445 | 0 / 2 | 445 | 0 / 2 |
| archive_2025 | 72 h | 445 | 0 / 3 | 445 | 0 / 3 |
| archive_2026 | 24 h | 440 | 3 / 2 | 440 | 3 / 2 |
| archive_2026 | 48 h | 440 | 6 / 6 | 440 | 5 / 6 |
| archive_2026 | 72 h | 440 | 10 / 10 | 440 | 8 / 10 |
| nrt_transition | 24 h | 140 | 83 / 53 | 140 | 23 / 29 |
| nrt_transition | 48 h | 140 | 103 / 76 | 140 | 48 / 44 |
| nrt_transition | 72 h | 140 | 111 / 89 | 140 | 57 / 70 |
| final_2026 | 24 h | 110 | 103 / 85 | 107 | 42 / 38 |
| final_2026 | 48 h | 110 | 108 / 93 | 107 | 60 / 59 |
| final_2026 | 72 h | 110 | 107 / 103 | 107 | 72 / 71 |

At the latest 24-hour quiet-cell snapshot budget, LR catches 42/86 positive windows with 65 false alerts (precision 39.3%, recall 48.8%); XGBoost catches 38/86 with 69 false alerts (precision 35.5%, recall 44.2%). Both issue 107 alerts. Its improved recall at cutoff 0.50 in the previous experiment therefore did not translate into better daily top-five early-warning performance here.

## Hourly sensitivity check

Hourly ranking uses every available timestamp; these totals strongly repeat the same fire activity. They are sensitivity diagnostics, not independent event counts.

| Period | Horizon | All-cell hits LR / XGB | Quiet-only hits LR / XGB |
| --- | ---: | ---: | ---: |
| archive_2025 | 24 h | 11 / 24 | 11 / 24 |
| archive_2025 | 48 h | 7 / 48 | 7 / 48 |
| archive_2025 | 72 h | 4 / 72 | 4 / 72 |
| archive_2026 | 24 h | 79 / 59 | 78 / 59 |
| archive_2026 | 48 h | 168 / 158 | 129 / 154 |
| archive_2026 | 72 h | 246 / 253 | 197 / 242 |
| nrt_transition | 24 h | 2052 / 1465 | 548 / 683 |
| nrt_transition | 48 h | 2527 / 2087 | 1205 / 1120 |
| nrt_transition | 72 h | 2731 / 2269 | 1407 / 1697 |
| final_2026 | 24 h | 2474 / 2147 | 982 / 921 |
| final_2026 | 48 h | 2590 / 2368 | 1418 / 1416 |
| final_2026 | 72 h | 2570 / 2484 | 1673 / 1758 |

Cadence changes some comparisons, which limits a blanket early-warning claim. The budget tables also include random expected hits, computed as k × positive cells / eligible cells at each snapshot. This is a descriptive reference conditioned on evaluation labels, not a deployable predictor.

## Verification and reproduction

All 127 Role B tests and 18 shared contract checks passed. New hand-checked tests cover per-snapshot allocation, misses outside top-k, label-blind ties, input row order, small/empty quiet pools, invalid inputs, overlapping evaluation periods and temporal embargoes. Paired-budget audits confirm identical opportunities and alert totals. Source hashes were preserved. Models and predictions stay under ignored `b_model/runs/budget_backtest_20261017/`. Shared feeds and prior model artifacts were preserved.

This fresh fit uses the same hyperparameters as the previous teammate run but a different canonical row ordering. Some XGBoost fits and scores differ; exact parameter/median/tree comparisons are saved in `retraining_audit.json`. Treat these as this backtest’s results rather than overwriting the earlier run’s metrics. This sensitivity is another reason to avoid promotion based on one fit.

Run `OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 MKL_NUM_THREADS=2 .venv/bin/python -m b_model.backtest` from the repository root. The runner refuses existing run/evidence directories; use a copied config with fresh paths to repeat. No new packages or data sources were added. The archive/NRT source-coverage uncertainty from the earlier source audit remains unresolved.

Evidence: [experiment_results/20261017_backtest/](experiment_results/20261017_backtest/), including the frozen protocol, split audits, `results.json`, `budget_summary.csv`, `daily_budget.csv`, `metadata.json` and `retraining_audit.json`.
