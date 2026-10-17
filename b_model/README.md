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
