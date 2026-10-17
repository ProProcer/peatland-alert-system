# Role A → B real-data check — 2026-10-17

The 33-cell handoff is compatible with B's configured training and inference.
This establishes interface compatibility; the first real model is not useful
enough for operational alerts. Schema 1.0, field names, units, UTC timestamps and
risk thresholds remain unchanged.

## Inputs and publication

- Source: `data/demo/role_a_real/hackathon/`, documented in
  [A's handoff](../a_data/REAL_HANDOFF.md).
- Training: `history_2025.parquet`, 289,080 rows, 33 cells, 27 predictors and all
  three supplied future targets. SHA-256:
  `4e64ca1a7ad7a2384993ea3c6a54a3058dba12c66dcdae2f25bd93afff113b43`.
- Extended history: 541,728 rows; 2,376 rows lack at least one target, leaving
  539,352 usable rows. No duplicate cell/hour keys were found. Every predictor
  has at least one observed value in the training partition of either history.
- Replay: 33 feature records at `2026-10-16T00:00:00Z`. B's actual schema aligner
  accepts them against both historical files, including 31 null measurements.
- The human requested replacing the development processed data. A's existing
  replay exporter supplied the four A-owned files; B supplied real risk, and
  C's existing deterministic policy supplied an empty simulated dispatch array.
  The staged bundle passed cross-file validation before publication.
- Active files and SHA-256 values are recorded in
  [processed provenance](../data/processed/provenance.json). Previous processed
  data and legacy models were backed up under ignored `b_model/runs/`.

The two agreed definitions are the trailing seven-day nearest hotspot and
`soil_air_temp_gap_c = soil_temp_18_c - temp_c`. ICON Global weather and FIRMS
export coverage are documented by A. FIRMS coverage is human-declared export
completeness, not an independent satellite observation-availability audit.

## Actual training run

The configured run used sklearn histogram gradient boosting (150 iterations,
depth 4, learning rate 0.05), balanced class weights, a logistic/dryness baseline,
and separate sigmoid calibration. Imputation/scaling were fitted on training only.
All cells at a timestamp stay in the same partition; both boundaries have a
72-hour embargo. No settings were tuned against the final validation result.

| Partition | UTC start | UTC end | Rows | Positive 24-hour labels |
| --- | --- | --- | ---: | ---: |
| Training | 2025-01-01T00:00:00Z | 2025-07-17T17:00:00Z | 156,618 | 218 |
| Calibration | 2025-07-20T18:00:00Z | 2025-09-28T17:00:00Z | 55,440 | 145 |
| Validation | 2025-10-01T18:00:00Z | 2025-12-31T23:00:00Z | 72,270 | 96 |

| Horizon | Primary PR-AUC | Baseline PR-AUC | Primary ROC-AUC | Precision / recall at 0.50 |
| --- | ---: | ---: | ---: | --- |
| 24 h | 0.001 | 0.004 | 0.453 | 0.000 / 0.000 |
| 48 h | 0.005 | 0.009 | 0.354 | 0.000 / 0.000 |
| 72 h | 0.004 | 0.053 | 0.500 | 0.000 / 0.000 |

Lead time is unmeasured (`null`) for all horizons. The baseline outperforms this
primary candidate. The first run is compatibility evidence, not an accepted model.
Saved bundles, settings and full metrics are in `b_model/model_real_2025/`;
the original run remains in ignored `b_model/runs/role_a_2025_compatibility/`.

## Inference and downstream result

A fresh CLI process took 2.552 seconds locally with native thread counts set to
two. It produced 99 records: 33 cells times horizons 24/48/72, all at the real replay
timestamp. Scores range from about 0.00172 to 0.00784, so all risks are LOW and C
produces no dispatch. No probability was changed to trigger an alert. This local
measurement is not LinuxONE performance evidence.

Use `python -m b_model.predict --config-name replay_role_a` to select the real
candidate and the matching processed inputs. The generic inference profile still
defaults to legacy `b_model/model/`; do not use it as real-model evidence.
The training preset is `--config-name training_role_a`. See the
[README commands](README.md#role-a-real-data-replay).

All 105 existing model tests passed in the isolated test workspace both before
and after publication. After publication, all 18 shared fixtures/processed feeds
passed validation. The real replay also passed the shared cross-file validator,
independently of those synthetic tests. Published A outputs are byte-identical
to their source bundle, and all six feed fingerprints match the provenance file.

## Remaining work and limits

- PIC 2: improve and compare candidates using earlier chronological development
  folds, then evaluate on an untouched period. The 2025 set has only 459 positive
  24-hour rows, representing overlapping event windows rather than 459 independent
  fires. More history alone does not establish a better model.
- Review the shift in hotspot frequency with A before choosing a final evaluation
  period: the supplied full-history split has about 0.16% positive 24-hour rows in
  training and 21.0% in validation. This check does not establish its cause.
- Missingness is substantial: in 2025, nearby count/FRP are each 45.45% null and
  nearest-hotspot distance is 95.66% null. Median imputation runs successfully;
  its scientific adequacy still needs evaluation. Unknown observations remain null
  in the published source files.
- C still needs to connect A's mapped-water `WaterIndex`. The publication run used
  an explicit empty catalogue, so no synthetic water source entered dispatch.
- E must add explicit historical replay orchestration: the current
  `scripts/run_pipeline.sh` invokes A's current-hour command, which intentionally
  fails while live ingestion is pending. Select B's real replay config and keep
  all dashboard feeds on this timestamp and these 33 cells.
- Heuristic `top_factors` are not SHAP values. LinuxONE installation and timing
  remain unverified by this local check.
