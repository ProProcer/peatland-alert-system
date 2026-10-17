# Final Role B hackathon handoff

Role B's implementation, retrospective evaluation and demo handoff are complete.
The delivered model is a provisional tool for historical replay and human review.
Operational fire-warning reliability has not been established.

## Model to use for the main demo

Use the explicit `replay_regional` profile and the machine-readable
[CURRENT_HANDOFF.json](CURRENT_HANDOFF.json). It identifies the matching inputs,
model artifacts, risk feed, source hashes and quality report for **40 cells across
five Indonesian Kalimantan provinces**, at **2026-10-16T00:00:00Z**.
Handoff SHA-256 values hash binary files as stored and normalize CRLF to LF for
JSON/GeoJSON, so Git's Windows text checkout does not create false mismatches.

```bash
python -m b_model.predict --config-name replay_regional
python -m contracts.validate --kind risk b_model/experiment_results/20261017_regional_40/risk.json
```

Install `b_model/requirements-training.txt` with the root constraints first.
The output has 120 records: one per cell and 24/48/72-hour horizon. C/D/E must
consume the matching A features/history/geometry and B risk together. The
separate 33-cell `data/processed/` feeds are not this regional handoff. Generic
inference defaults to `b_model/model/`, an uploaded ensemble with different
evaluation results; use the named profile above for the final demo.

The shared contract remains schema 1.0: UTC `Z` timestamps, named JSON
coordinates, null measurements, 27 canonical producer features and unchanged
risk boundaries of 0.35/0.60/0.80. Notifications and dispatch stay simulated.
Soil inputs are modeled weather, and the target is future FIRMS surface-hotspot
occurrence, including ongoing activity; it is not direct underground-fire sensing
or a validated measure of new ignitions. Explanations are directional heuristics.

## Evaluation and review candidate

[REGIONAL_RESULTS.md](REGIONAL_RESULTS.md) documents the delivered model.
[RECENCY_RESULTS.md](RECENCY_RESULTS.md) records the completed five-strategy,
60-fit comparison and separate probability/policy calibration with 72-hour gaps.
Development data selected recent 365-day training for 24/48 hours and 180-day
training for 72 hours. The separate `model_recency_candidate/` remains for review.

At the same five-alert daily quiet-cell budget (110 selections per horizon),
selected-model hits versus matched full-history control were 47/43, 58/55 and
70/66; false alerts were 63/67, 52/55 and 40/44. These count overlapping forecast
windows, not independent fires. Calibration-selected thresholds reduce workload
and miss more positive windows; they do not consistently improve performance.
No research threshold has been enabled in C or substituted for shared risk levels.

The independent completion check reproduced development-only selection,
selected-model calibration thresholds, later-date scores/budgets and the
120-record consumer replay. It checked all 60 saved comparisons against their
daily aggregates, all candidate/source fingerprints, and preservation of the
current handoff/shared feeds. Full-history control models were not refitted in
that verification. Evidence is in
[completion_verification.json](experiment_results/20261017_recency/completion_verification.json).
All **144 model tests passed with no skips**, and all **18 shared contract
fixtures/processed feeds** validated. Local timing is not LinuxONE evidence.

## Remaining work for the wider team

- **A / source owner:** archive/NRT attribution is unresolved. The products do
  not overlap locally, and original export settings were not saved. Supply
  original export receipts/settings or controlled paired exports as specified
  in [role_a_request.json](experiment_results/20261017_source_consistency/role_a_request.json).
  The audit found no obvious confidence-code, satellite-switch or duplicate-key
  explanation; it cannot prove identical upstream coverage. Labels are unchanged.
- **C/D/E:** integrate the exact regional bundle identified in `CURRENT_HANDOFF.json`,
  demonstrate simulated actions and finish deployment/submission evidence.
- **Future model acceptance:** evaluate the frozen model and operating point on
  later reserved observations with verified export coverage, including quiet-cell
  recall, false alerts at the intended workload, calibration and independent
  event-based lead time. Retuning against the already-inspected final period
  does not establish reliable new-fire early warning.

These are explicit integration/research limitations, not claims of missing
software functionality or operational approval. The recency candidate has not
been promoted, and no external notification or message to Role A was sent.
