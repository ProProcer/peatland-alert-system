PYTHON ?= .venv/bin/python
ROLE ?= all
PORT ?= 8000
LIVE_PORT ?= 8001

.PHONY: setup validate test model-test mock demo serve-live pipeline live live-once

setup:
	bash scripts/setup.sh $(ROLE)

validate:
	$(PYTHON) -m contracts.validate

test:
	$(PYTHON) -m unittest discover -s e_platform/tests -v

model-test:
	$(PYTHON) scripts/test_model.py

mock:
	PYTHON="$(PYTHON)" bash scripts/run_pipeline.sh --mock

demo: mock
	$(PYTHON) -m e_platform.serve --data-dir data/demo --port $(PORT)

serve-live:
	$(PYTHON) -m e_platform.serve --data-dir data/processed --port $(PORT)

pipeline:
	PYTHON="$(PYTHON)" bash scripts/run_pipeline.sh

live:
	$(PYTHON) -m e_platform.live_service --port $(LIVE_PORT)

live-once:
	$(PYTHON) -m e_platform.live_service --once
