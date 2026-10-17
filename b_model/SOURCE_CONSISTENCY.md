# FIRMS archive/NRT source consistency — 2026-10-17

**Status: source attribution and original export coverage remain unresolved.** The human relayed Role A confirmation that the original query/bounding-box/filter settings and download timestamps were not saved, and the products have no overlapping export dates. No local comparison can separate real seasonal fire activity from unrecorded source/export differences with these files alone.

## What was checked

All four original CSV files were read and their SHA-256 hashes verified against the existing source manifest. Full-file satellite, instrument, collection/version, confidence and type counts, observed coordinate envelopes and dates are recorded in `audit.json`. Normalized acquisitions have zero duplicate `(satellite, ts, latitude, longitude)` keys.

| Satellite | Product | Rows | Observed first date | Observed last date | Version |
| --- | --- | ---: | --- | --- | --- |
| N20 | archive | 1,342,756 | 2018-04-01 | 2026-06-30 | 2 |
| N20 | nrt | 520,571 | 2026-07-01 | 2026-10-16 | 2.0NRT |
| N21 | archive | 489,095 | 2023-03-01 | 2026-06-30 | 2 |
| N21 | nrt | 515,983 | 2026-07-01 | 2026-10-16 | 2.0NRT |

Both N20 and N21 occur before and after July 1. Confidence is consistently coded with n/h/l. The filenames identify Collection 2, while the version fields distinguish archive `2` from `2.0NRT`. Observed envelopes broadly span Indonesia in both products; envelopes describe detections, not original query coverage or a completeness guarantee.

Raw archive files contain types 0, 1, 2 and 3, so the earlier observation of only type 0 in a small selected-cell subset is not evidence that the whole archive export was filtered to type 0. The new 40-cell normalized subset has 1,003 archive detections, all recorded type 0, and 16,488 NRT detections without type. Those figures include low-confidence and context detections; contracted labels still use n/h only. Type comparability cannot be established for the NRT rows.

Role A’s normalizer applies the same n/h eligibility check and downstream Kalimantan geometry to both products. There is no obvious confidence-parser/satellite-switch/duplicate explanation for the increase in this audit. A common downstream polygon filter cannot restore observations excluded from an unknown upstream export.

## Official processing context

NASA distinguishes NRT from standard processing and documents a multi-month availability lag for standard products. An archive-to-NRT boundary is therefore compatible with normal availability; its existence is not itself a processing defect. Product dates must be checked before assuming paired observations are available. [NASA FIRMS API tutorial](https://firms.modaps.eosdis.nasa.gov/content/academy/data_api/firms_api_use.html), [official availability endpoint](https://firms.modaps.eosdis.nasa.gov/api/data_availability/).

The public documentation was reviewed. No live keyed availability/data request was executed: no usable FIRMS key was configured. No credentials were printed or saved.

## Evidence needed from Role A

The exact request is saved in [experiment_results/20261017_source_consistency/role_a_request.json](experiment_results/20261017_source_consistency/role_a_request.json). Supply original export settings/receipts if recoverable, or re-export a common available seven-day period with identical geographic, confidence, collection and day/night settings for both satellites/products. Record metadata, hashes and download time; retain type fields. Apply the same frozen cell grid afterward and compare acquisition matches as well as counts.

If historical paired NRT is unavailable, preserve a new NRT export with explicit settings and compare it with standard processing when it becomes available. A consistent-product or future paired evaluation can narrow the uncertainty; retraining/class weighting alone cannot prove export completeness.

No external message was sent. No A source/configuration, label definition, missing value or shared contract was changed. Existing model evaluation remains conditional on the team’s declared coverage, not independently verified satellite/export availability.

Evidence: [experiment_results/20261017_source_consistency/](experiment_results/20261017_source_consistency/). Reproduce with `python -m b_model.source_consistency` after choosing a fresh audit directory in the script; it refuses to overwrite an existing audit.
