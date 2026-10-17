# Chronological model experiment — 2026-10-17

Regularized Logistic Regression with sigmoid calibration was selected for all three horizons. It outperformed the earlier published candidate, the logistic/dryness baseline, and the past-hotspot persistence rule in ranking on the final evaluation period. Performance is weaker on cells with no recent hotspots; this remains a provisional historical replay candidate.

Published models and `data/processed/` feeds were preserved. Portable copies of the selected bundles are tracked in `b_model/model_candidate_2026/`, and the matching 99-row risk is in `b_model/experiment_results/20261017/risk.json`. The original experiment remains under ignored `b_model/runs/chronological_experiment/`.

## Protocol and evidence

- Input: Role A's real 33-cell history, with 541,728 rows before excluding 2,376 rows with incomplete future targets. Its SHA-256 is `444152463a2aa952a6154c965d7c3876e48e4ffea1c86370ca811dafa76bfb40`.
- Compared six primary settings: Logistic Regression C=0.001/0.01/0.1 and three simpler boosting settings. Each was evaluated with sigmoid and isotonic calibration, alongside a similarly calibrated logistic/dryness baseline.
- Three development windows, three horizons and fourteen model/calibration combinations produced 126 development comparisons. Parameters and dates were fixed before these results were calculated.
- Selection per horizon used mean calibrated development average precision (AP, labeled PR-AUC here), then mean Brier score, then candidate name. Selection was saved before final-period model prediction metrics were calculated.
- Development evaluation ended before final calibration/evaluation. All temporal boundaries have at least 72-hour gaps; preprocessing and primary fitting use training only. Boosting's random internal early-stopping holdout is disabled.
- The final period was reserved from candidate selection. Aggregate monthly labels and source distributions had already been inspected, so this is a retrospective evaluation rather than a prospective field trial.
- Protocol, source audit, selection, final metrics, partition counts and development summary are saved in [experiment_results/20261017/](experiment_results/20261017/).

## Final dated partitions

| Partition | First UTC hour | Last UTC hour | Rows |
| --- | --- | --- | ---: |
| train | 2024-12-02T00:00:00Z | 2026-08-31T23:00:00Z | 505,296 |
| calibration | 2026-09-04T00:00:00Z | 2026-09-18T23:00:00Z | 11,880 |
| validation | 2026-09-22T00:00:00Z | 2026-10-13T23:00:00Z | 17,424 |

## Selected configurations

| Horizon | Primary | C | Calibration | Mean development PR-AUC |
| --- | --- | ---: | --- | ---: |
| 24 h | Logistic Regression, 27 features, balanced classes | 0.001 | sigmoid | 0.1805 |
| 48 h | Logistic Regression, 27 features, balanced classes | 0.001 | sigmoid | 0.2374 |
| 72 h | Logistic Regression, 27 features, balanced classes | 0.1 | sigmoid | 0.2584 |

## Final evaluation: same period for all comparisons

The final evaluation contains 17,424 hourly cell records from September 22 through October 13, 2026. Positive prevalence is high (69–85%, depending on horizon), so high AP alone is insufficient evidence of usefulness. These observations include ongoing fires and are temporally correlated; rows are not independent fire events. The earlier candidate was reevaluated on this same period, rather than comparing its old 2025 metrics directly with these results.

| Horizon | Positive rate | Previous AP | Dryness AP | Persistence AP | Selected AP | Selected ROC-AUC | Selected Brier |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 24 h | 0.687 | 0.770 | 0.635 | 0.825 | 0.901 | 0.814 | 0.164 |
| 48 h | 0.794 | 0.777 | 0.788 | 0.901 | 0.941 | 0.820 | 0.133 |
| 72 h | 0.850 | 0.925 | 0.848 | 0.940 | 0.958 | 0.836 | 0.108 |

The persistence rule uses whether a hotspot was observed in the preceding 24 hours. It is a reference rule, not an exported probability model. AP is a ranking metric; Brier measures squared probability error (lower is better). The current comparison combines different regularization, a longer training history and later calibration; improvement cannot be attributed to model choice alone.

| Horizon | Precision at 0.50 | Recall at 0.50 | Precision at HIGH (0.60) | Recall at HIGH (0.60) |
| --- | ---: | ---: | ---: | ---: |
| 24 h | 0.845 | 0.787 | 0.849 | 0.725 |
| 48 h | 0.890 | 0.873 | 0.904 | 0.811 |
| 72 h | 0.925 | 0.888 | 0.932 | 0.842 |

No score transformation was used to force HIGH/CRITICAL output. Frozen risk boundaries and feature names are unchanged.

## Early-warning subgroup: no hotspot in preceding 24 hours

Each horizon uses the same 5,545 quiet-hour records. This subgroup is closer to an early-warning use case, but still predicts a future surface hotspot, not independent new ignitions or underground combustion.

| Horizon | Positive rate | PR-AUC | ROC-AUC | Precision at 0.50 | Recall at 0.50 | Brier |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 24 h | 0.337 | 0.417 | 0.628 | 0.414 | 0.297 | 0.241 |
| 48 h | 0.508 | 0.605 | 0.640 | 0.630 | 0.499 | 0.262 |
| 72 h | 0.602 | 0.724 | 0.669 | 0.733 | 0.567 | 0.248 |

At 24 hours, only about 30% of positive quiet-hour windows are caught at cutoff 0.50, despite 79% recall overall. Quiet-subgroup Brier error is worse than a constant probability equal to that subgroup's observed prevalence; this is a diagnostic reference using evaluation prevalence, not a deployable fitted baseline. Subgroup calibration and event-based early-warning evaluation need more work.

## NOAA-20 / NOAA-21 source check

- All 29,294 detections inside these 33 cells (including lookback context) identify VIIRS, split across N20 and N21. No duplicate `(satellite, timestamp, latitude, longitude)` acquisition keys were found.
- Both satellites are present before 2026. Only 34 detections occur in these cells during 2025; 459 positive 24-hour rows are overlapping label windows, not 459 independent fires.
- Archive files end in June 2026; NRT files begin in July. The archive subset has 72 type=0 records including context, while 29,222 NRT records lack the type field. The model still uses the agreed n/h labels from both products; no source-specific relabeling or filtering was introduced.
- The timing of the increase aligns with the archive/NRT boundary, but this audit cannot establish whether fire activity, source processing, export completeness or a combination explains it. NASA documents that NRT and standard science-quality data are different processing stages ([FIRMS data documentation](https://firms.modaps.eosdis.nasa.gov/active_fire)). Export completeness remains human-declared.

## Artifacts, checks and next use

- Portable model bundles: `b_model/model_candidate_2026/`; replay: `b_model/experiment_results/20261017/risk.json`. The opt-in profile is `replay_candidate`.
- The actual PIC 1 consumer accepted the exported models and validated 99 records for 33 cells at `2026-10-16T00:00:00Z`.
- A fresh CLI process completed in 2.422 seconds locally with native thread counts set to two. This is not LinuxONE timing evidence.
- Replay levels: CRITICAL=57, HIGH=13, LOW=9, MODERATE=20. These are prediction counts, not performance metrics.
- All 111 model tests passed in an isolated workspace. The experiment risk passes schema 1.0. Published feed fingerprints and Role A's historical input fingerprints remain unchanged.
- Candidate selection was frozen before final results. No additional tuning was performed after looking at the final metrics.

```bash
python -m b_model.predict --config-name replay_candidate
python -m contracts.validate --kind risk b_model/experiment_results/20261017/risk.json
```

This candidate is suitable for the next isolated historical replay integration test. Before operational claims, resolve source comparability, evaluate independent events/false alerts and quiet-hour calibration, and obtain LinuxONE execution evidence. The published candidate and shared feeds were not promoted by this experiment.
