# Role B repair and updated 40-cell results — 2026-10-17

The updated Role A scope is now supported by a new, separately packaged Logistic Regression candidate for all three horizons. It produces 120 matching predictions for 40 cells across five Kalimantan provinces. All 138 software tests pass, with no skips. The incoming uploaded XGBoost model remains rejected by its separate quality gate; it was preserved rather than changing its measurements.

## Software fixes

- Replaced the outdated 27-column direct-imputer test with an actual inference round trip that supports the saved 27/29-predictor pipeline and its required historical context.
- Replaced the assumption that every artificial dry spell must become CRITICAL with checks that the specified cells receive the scenario inputs, other cells remain unchanged, and output probabilities/levels obey the contract. This does not force any score or risk class.
- Added `quality.py` as a separate explicit model acceptance command. Poor baseline comparisons or zero recall remain failures of model acceptance rather than fabricated software expectations. Invalid metrics fail validation; valid null/nonmonotonic measured lead times are preserved.
- Installed optional `py-ubjson==0.16.1` and declared `requirements-repair.txt`; the previously skipped trusted artifact-recovery test now executes and passes. It is not needed for ordinary inference.
- Added coverage for portable 29-predictor XGBoost export through the actual inference reader, plus quality-gate rejection and invalid-value tests. Existing 27-predictor models remain supported.
- The backtest now records accuracy and constant-prediction references, optionally includes a separately calibrated dryness baseline, and freezes model selection before the final evaluation. XGBoost version reporting works with either CPU-only or full distributions.

## Updated inputs and scope

Role A delivered 656,640 rows and 40 cells (eight in each province), with 653,760 rows having all three labels observed. The 2,880 rows with incomplete labels are excluded rather than made negative. Only two of these cells overlap the old 33-cell sample. Earlier 33-cell metrics are historical and are not evaluations of these new points.

All feature/history/geometry/selection IDs match. Rebuilt all 1,969,920 target entries from the VIIRS n/h in-scope events and verified exact agreement, including nulls and (t,t+h] endpoints. All 27 canonical feature names, units, UTC Z timestamps, 0.1-degree cells and fixed risk boundaries are unchanged. Source weather is modeled ICON Global weather, not sensor telemetry.

Source history SHA-256: `83c226e5c9fd72c00bbfd487c0fa488147ac7ac90fe939ae64a25f2e0074f945`. Full checks and input fingerprints are in `input_check.json`. The geographic sample supports a spread-out demo, not an area-weighted or representative estimate of fire incidence. Targets are hotspot occurrence anywhere inside each cell, not strictly peat-only fire or independent new ignition.

## Training and selection

Ran 36 model/horizon fits: three approaches × three horizons × four chronological periods. Approaches were balanced 27-feature Logistic Regression, the teammate 29-feature weighted XGBoost, and a Logistic Regression dryness baseline. LR C=0.001 / 0.001 / 0.1; XGBoost settings and all dates are frozen in `conf/backtest_regional.yaml`, with no final-period tuning. Preprocessing is fit on training only; sigmoid calibration uses a separate chronological slice. Both temporal gaps are at least 72 hours.

Per-horizon backend selection uses mean AP across the first three development periods, then Brier to break ties. `selection.json` was saved before final-period fitting/scoring. It selected Logistic Regression for all horizons. Mean development AP was 24h: 0.3318, 48h: 0.3637, 72h: 0.3640. These are retrospective dates already used for earlier geography, not an independent prospective test.

| Final partition | First UTC hour | Last UTC hour | Rows |
| --- | --- | --- | ---: |
| train | 2024-12-02T00:00:00Z | 2026-08-31T23:00:00Z | 612480 |
| calibration | 2026-09-04T00:00:00Z | 2026-09-18T23:00:00Z | 14400 |
| validation | 2026-09-22T00:00:00Z | 2026-10-13T23:00:00Z | 21120 |

## Final evaluation on the new 40 cells

Classification uses cutoff 0.50. The constant reference is the better of always predicting hotspot and always predicting no hotspot on this evaluation period; here the better constant is always no hotspot. It is a descriptive reference, not a threshold fitted on evaluation labels. AP is Average Precision, not accuracy. All model/baseline ranking comparisons below use exactly the same final rows.

| Horizon | Accuracy | Best constant accuracy | Precision | Recall | AP | Brier |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 24 h | 79.1% | 63.4% | 84.3% | 52.9% | 0.8480 | 0.1310 |
| 48 h | 83.0% | 56.0% | 89.3% | 69.8% | 0.9024 | 0.1177 |
| 72 h | 86.1% | 52.4% | 92.9% | 76.6% | 0.9273 | 0.1026 |

| Horizon | Selected LR AP | XGBoost AP | Calibrated dryness AP | Recent-hotspot persistence AP |
| --- | ---: | ---: | ---: | ---: |
| 24 h | 0.8480 | 0.7562 | 0.6846 | 0.7182 |
| 48 h | 0.9024 | 0.8554 | 0.7577 | 0.7909 |
| 72 h | 0.9273 | 0.8959 | 0.7722 | 0.8097 |

The selected models beat these ranking references and the constant accuracy reference on this period. The minimal quality gate passes all three horizons. This does not certify calibration, future seasonal robustness or operational use. The 33-cell model and this 40-cell model should not be compared as a direct before/after accuracy gain.

## Early warning and fixed budgets

The quiet subgroup contains 13,540 hourly cell/windows without a hotspot in the preceding 24 hours. It is closer to early warning, but still includes repeated windows and can include recurrent activity.

| Horizon | Quiet AP | Quiet precision at 0.50 | Quiet recall at 0.50 | Daily quiet top-five hits / positive windows | Daily quiet false alerts |
| --- | ---: | ---: | ---: | ---: | ---: |
| 24 h | 0.4149 | 39.8% | 9.4% | 43 / 68 | 67 |
| 48 h | 0.5558 | 65.4% | 30.8% | 55 / 103 | 55 |
| 72 h | 0.6485 | 77.3% | 40.1% | 66 / 125 | 44 |

At 24 hours, cutoff 0.50 catches only 9.4% of quiet positive windows. A separate hypothetical allocation of five quiet cells at 00:00 UTC catches 43/68 daily positive windows with 67 false alerts across 110 selections. This illustrates the threshold/budget tradeoff; it does not change Role C dispatch policy or fixed risk boundaries.

| Horizon | Daily all-cell hits: LR / XGB / dryness | Daily quiet hits: LR / XGB / dryness |
| --- | ---: | ---: |
| 24 h | 99 / 87 / 91 | 43 / 42 / 37 |
| 48 h | 103 / 99 / 103 | 55 / 59 / 44 |
| 72 h | 105 / 105 / 107 | 66 / 69 / 52 |

All daily pools give each model the same up-to-five-cell budget independently per horizon. LR is not the best in every budget comparison: the dryness baseline catches 107 all-cell positive windows at 72 hours versus LR’s 105. Backend selection was based on earlier AP rather than choosing a final-period winner after inspection. Per-day counts, hourly sensitivity, false alerts, random expected hits, and per-province metrics are saved in the evidence. These counts are correlated cell/windows, not unique fires or avoided incidents.

## Replay and team handoff

Fresh CLI inference on the October 16 replay took 2.58 seconds locally with two OMP/BLAS threads. Output has 120 records, 40 exact matching IDs, all three horizons, UTC Z timestamps and valid schema 1.0. Risk levels: {'LOW': 75, 'CRITICAL': 24, 'MODERATE': 14, 'HIGH': 7}. This replay lacks complete observed future labels; these levels are predictions, not validation outcomes. Timing is not an IBM LinuxONE result.

```bash
.venv/bin/python -m b_model.predict --config-name replay_regional
.venv/bin/python -m b_model.quality b_model/model_regional_40/metrics.json
```

Use [CURRENT_HANDOFF.json](CURRENT_HANDOFF.json) for exact matching A/B paths and fingerprints. The new artifacts are in `b_model/model_regional_40/`; regional risk is in `b_model/experiment_results/20261017_regional_40/risk.json`. Portable bundles include source/split/selection provenance. LR explanations remain the existing signed standardized heuristic with feature priorities; they are not exact calibrated-logit decompositions or causal explanations.

Role B changes stay within `b_model/`. Shared `data/processed/` remains the separate 33-cell replay. C/D/E must switch the matching 40-cell features, history, geometry and risk together; replacing only risk would produce an invalid mixed scope. Role B has not altered A/C outputs or deployed a new system. The handoff is ready for their scoped integration.

## Validation and remaining limits

All **138 software tests pass, with no failures or skipped tests**, including trusted artifact repair and both feature-pipeline export paths. All 18 shared contract checks passed; new 40-cell feature/geometry/risk checks also passed. The old incoming model’s quality rejection is retained in `incoming_model_quality_gate.json`; the new candidate’s minimal acceptance report is in `quality_gate.json`. Software tests being green does not erase model-performance failures.

FIRMS export completeness is human-declared. The archive/NRT source uncertainty is still unresolved. All evaluations use the same selected cells at different times, not held-out provinces or an independent future season. Earliest archive folds and no-recent-hotspot cases remain weaker. No accuracy guarantee or deterministic fire claim is justified.

Evidence: [experiment_results/20261017_regional_40/](experiment_results/20261017_regional_40/). Reproduce fitting with a copy of `conf/backtest_regional.yaml` pointing to fresh run/evidence paths, then `python -m b_model.backtest --config <copy.yaml>` and `python -m b_model.regional_handoff --config <copy.yaml> --model-dir b_model/runs/new_regional_model`. Existing model/output directories are refused.
