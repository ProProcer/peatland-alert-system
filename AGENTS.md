# Team workspace

Read `TEAM_PLAYBOOK.md`, `contracts/CONTRACTS.md`, and the assigned role's README before changing implementation.

- Assigned role agents edit only their role folder and the shared output files that role owns. Role E owns `contracts/`, `config/`, `scripts/`, root integration files and CI. Repository setup and maintenance may span these folders when the human requests it.
- Keep the existing Role B implementation and artifacts intact during repository setup.
- Schema `1.0` is frozen. Never rename fields or change thresholds silently; discuss a contract change with the human and bump the version before adopting it.
- Supply a valid `mock_output.json` first. Use another role's mocks while its production adapter is incomplete.
- All timestamps are UTC with `Z`. GeoJSON uses `[lon, lat]`; JSON uses named `lat` and `lon`. Missing measurements are `null`.
- Role A owns `features.json`, `features.parquet`, `history.parquet`, and `cells.geojson`; B owns `risk.json`; C owns `dispatch.json`.
- Put experiments in temporary paths or `data/demo/`, not over the checked-in processed data or model artifacts.
- Run `make validate` after contract-facing changes and appropriate role tests after code changes. Never present mock metrics as evaluated performance.
- Record added open-source libraries and datasets, including links, in `README.md` (coordinate with E).
- Notifications remain simulated; no real SMS or dispatch is sent.
