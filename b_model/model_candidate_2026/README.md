# Improved historical replay candidate

These portable bundles were selected by the chronological experiment in
[`../experiment.py`](../experiment.py). They use all 27 canonical predictors,
median imputation, balanced Logistic Regression and separate sigmoid calibration.
C is 0.001 for 24/48 hours and 0.1 for 72 hours. Training ends on August 31, 2026;
calibration uses September 4–18, with 72-hour gaps before calibration/evaluation.
The final September 22–October 13 period was excluded from candidate selection.

See [`../EXPERIMENT_RESULTS.md`](../EXPERIMENT_RESULTS.md) for full comparisons
and limits. Overall final PR-AUC is 0.901/0.941/0.958, but 24-hour recall at 0.50
is only about 30% for records with no hotspots in the preceding day. This
candidate is for historical replay integration testing. Its final evaluation
period has much higher hotspot prevalence than 2025.

The manifest declares the model version and exact feature ordering. Provenance
records the data fingerprint, fitted/evaluation dates, and artifact hashes.
The shared feeds and earlier published candidate remain available separately.

```bash
python -m b_model.predict --config-name replay_candidate
python -m contracts.validate --kind risk b_model/experiment_results/20261017/risk.json
```

The default output is the separate 99-record candidate replay. C/E can select
this model directory explicitly for an integration run while keeping features,
geometry, risk and dispatch on the same timestamp and cell IDs. Use the pinned
training dependencies and trusted Joblib artifacts.
