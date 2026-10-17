# Peat Fire Early-Warning Agent

IBM Z Datathon 2026. Predict surface hotspot emergence in Indonesian peatland cells over 24, 48 and 72 hours, then simulate notifications and dispatches.

Read [TEAM_PLAYBOOK.md](TEAM_PLAYBOOK.md) first. The original [PDF](TEAM_PLAYBOOK.md.pdf) is retained. Shared interfaces are documented in [contracts/CONTRACTS.md](contracts/CONTRACTS.md).

## Start here

Requires Python 3.12 and Bash. Docker is optional. Run from the repository root:

```bash
# Install the shared tools and your role's dependencies (a, b, c, d, e, or all).
bash scripts/setup.sh e
source .venv/bin/activate

# Check every checked-in fixture and the existing processed JSON.
make validate

# Produce a separate, consistent mock handoff and open the starter UI.
make demo
```

Visit `http://127.0.0.1:8000`. Stop the server with Ctrl+C. `make demo` needs only the shared tools; it makes no external API calls and sends no notifications. The frontend is a handoff viewer for development; Role D builds the command-center map and role views.

The mock pipeline writes to `data/demo/` and leaves the existing `data/processed/` files and Role B artifacts intact. To view the existing processed data, run `make serve-live`; dispatch and cell geometry will appear after their owners produce them. Every panel falls back to a labeled static mock when its live file is unavailable.

## Ownership and handoffs

| Role | Folder and guide | Inputs | Outputs owned by the role |
| --- | --- | --- | --- |
| A — Data engineer | [a_data/README.md](a_data/README.md) | Peat GeoJSON, Open-Meteo, FIRMS | `features.json`, `features.parquet`, `history.parquet`, `cells.geojson` |
| B — ML lead | [b_model/README.md](b_model/README.md) | Features and history | `risk.json`, model artifacts, model card |
| C — Agent engineer | [c_agent/README.md](c_agent/README.md) | Risk, features, cells | `dispatch.json`, decision policy, simulated logs |
| D — Frontend / alerts | [d_frontend/README.md](d_frontend/README.md) | Cells, risk, dispatch, features | Web app and static fallback fixtures |
| E — Platform / pitch | [e_platform/README.md](e_platform/README.md) | All role outputs | Contracts, integration, containers, deployment evidence, submission |

Work in your own role folder. Shared output files have the owners listed above; request changes to another role's interface instead of renaming fields. Role E maintains root integration files and `contracts/`. Each role has a `mock_output.json`; D's mock is its risk-feed input, and E's mock is its dispatch integration fixture, since those roles have no additional JSON output contract.

```text
contracts/           Frozen version 1.0 schemas, examples, validator
a_data/              A: data adapter entry point, fixtures, tests
b_model/             B: existing training/inference code and artifacts
c_agent/             C: agent entry point, policy, fixtures, tests
d_frontend/          D: starter handoff viewer, static mocks
e_platform/          E: server, Dockerfiles, evidence and submission folders
scripts/             Setup and pipeline commands (E)
config/              Shared demo decisions (E)
data/raw/            Bundled peat/FIRMS sources; other downloads ignored
data/processed/      Existing/generated role outputs
data/demo/           Disposable mock pipeline outputs (ignored)
```

## Commands

| Command | Purpose |
| --- | --- |
| `make setup ROLE=a` | Create `.venv`, install shared tools and Role A dependencies |
| `make setup` | Install all Python role dependencies |
| `make validate` | Validate checked-in contracts, role mocks, frontend mocks, and existing outputs |
| `make test` | Run integration and contract checks for the scaffold |
| `make mock` | Build and validate `data/demo/` without external services |
| `make demo PORT=8001` | Run the mock pipeline and start the handoff viewer |
| `make serve-live` | Serve the frontend against `data/processed/` |
| `make pipeline` | Run A refresh → B predict → C agent and validate each handoff |
| `make model-test` | Run the existing Role B tests (install B dependencies first) |
| `docker compose up --build` | Run the mock pipeline and viewer in a container |

`make pipeline` deliberately fails at the first unimplemented live adapter. A's `refresh.py` and C's `agent.py` currently support `--mock` only. Replace those adapters in the owning folders when ready. B's existing inference remains available with `python -m b_model.predict`; use explicit `--input` and `--output` paths for experiments. Training is separate from the refresh pipeline.

## Shared decisions

- Initial demo province: **Central Kalimantan**, matching the existing fixture coordinates. See [config/demo.json](config/demo.json). The bounding box is a working selection box, not a province boundary dataset.
- Grid: 0.1° squares; `cell_id = "{lat_center:.2f}_{lon_center:.2f}"`; peat fraction at least 0.05; at most 300 demo cells.
- UTC timestamps end in `Z`. JSON has `lat`/`lon`; GeoJSON positions use `[lon, lat]`. Missing measurements are `null`.
- Schema version `1.0`; horizons 24/48/72; risk thresholds: LOW < 0.35, MODERATE < 0.60, HIGH < 0.80, otherwise CRITICAL.
- Water sources are `null` in mocks. C decides whether to add OSM data or a documented handmade fixture.
- Alerts are simulated. Open-Meteo soil moisture is modeled data. FIRMS detects surface anomalies, not underground smoldering. Peat depth is absent from the supplied source format.
- Treat the checked-in history, metrics and model artifacts as development inputs until B verifies their provenance and reproduces evaluation. Mock fixtures are synthetic and are not performance evidence.

## Dependencies and source attribution

Keep this inventory current as dependencies or datasets are added. Suggested role-specific dependencies are installed by the setup script; optional integrations need their own attribution when introduced. `constraints.txt` pins scikit-learn to the version recorded in the checked-in model artifacts; coordinate any upgrade with B and retrain before using new artifacts.

| Library / tool | Use | Project link |
| --- | --- | --- |
| Python standard library | CLI, local server, mock workflow, integration tests | [Python](https://www.python.org/) |
| NumPy | Numerical features and modeling | [NumPy](https://numpy.org/) |
| pandas | Hourly data and model inputs | [pandas](https://pandas.pydata.org/) |
| Apache Arrow / PyArrow | Parquet handoffs | [Apache Arrow](https://arrow.apache.org/) |
| GeoPandas | Role A spatial joins and projected areas | [GeoPandas](https://geopandas.org/) |
| Shapely | Role A geometry and spatial indexing | [Shapely](https://shapely.readthedocs.io/) |
| Requests | Role A HTTP data retrieval | [Requests](https://requests.readthedocs.io/) |
| scikit-learn | Existing baseline / gradient boosting | [scikit-learn](https://scikit-learn.org/) |
| joblib | Existing model artifacts | [joblib](https://joblib.readthedocs.io/) |
| jsonschema | Shared Draft 2020-12 contract validation | [jsonschema](https://python-jsonschema.readthedocs.io/) |
| pytest | Existing Role B tests | [pytest](https://docs.pytest.org/) |
| Docker / Compose | Optional local integration container | [Docker](https://docs.docker.com/) |
| IBM Snap ML (optional) | Role B hardware acceleration, not installed by default | [Snap ML](https://www.zurich.ibm.com/snapml/) |
| SHAP (optional) | Role B explainability, not installed by default | [SHAP](https://shap.readthedocs.io/) |

| Dataset / service | Use | Source link |
| --- | --- | --- |
| Open-Meteo | Modeled hourly weather / soil moisture and historical data | [Forecast API](https://open-meteo.com/en/docs), [historical API](https://open-meteo.com/en/docs/historical-weather-api) |
| Global Forest Watch | Indonesian peat polygon source described in the playbook | [GFW data](https://www.globalforestwatch.org/) — A records the exact layer URL and license when downloaded |
| NASA FIRMS | VIIRS thermal surface hotspots | [FIRMS](https://firms.modaps.eosdis.nasa.gov/), [API](https://firms.modaps.eosdis.nasa.gov/api/) |

Store download timestamps, exact source URLs and licenses beside cached datasets. Do not commit a FIRMS MAP_KEY; copy `.env.example` to `.env` locally. The setup script creates that file if absent, but does not load credentials or contact a data provider. Live adapter configuration and authentication belong to A.

LinuxONE / `s390x` installation, model execution, screenshots and IBM lab completion still require verification on the team's instance. See [e_platform/README.md](e_platform/README.md) for the evidence and submission checklist.
