# Role C — Agent engineer

Read `TEAM_PLAYBOOK.md` and `contracts/CONTRACTS.md`. Own this folder and `data/processed/dispatch.json`. Decisions use risk, features and cells; notifications remain simulated.

```bash
bash scripts/setup.sh c
# Windows PowerShell: .\.venv\Scripts\Activate.ps1
# Unix/macOS: source .venv/bin/activate
make mock
python -m c_agent.agent --mock --data-dir data/demo --output data/demo/dispatch.json
python -m c_agent.agent --data-dir contracts/examples --output data/demo/dispatch.json
python -m contracts.validate --kind dispatch data/demo/dispatch.json
python -m unittest discover -s c_agent/tests -v
```

On Windows without activating the venv, call `.venv\Scripts\python.exe` instead of `python` so `jsonschema` resolves.

`--mock` validates the three inputs and replays `mock_output.json` (fixed CRITICAL fixture with all five bilingual messages and `water_source: null`). Live mode runs the deterministic policy in `policy.py`, persists dedupe/cooldown state under `state/` (gitignored), and appends simulated notification lines to `logs/`.

Additional CLI options:
- `--cluster-distance-km` (default 15): Cluster CRITICAL cells within this distance; 0 disables clustering
- `--max-water-km` (default 15): Attach water source only if within this distance; 0 disables cutoff
- `--cooldown-hours` (default 6): Cooldown period before re-notifying same cell

## Extended Features (Beyond Team Playbook)

### Social Media Post Generation
Generate Twitter/X and Facebook posts for dispatches:
```bash
python -m c_agent.agent --data-dir data/demo --output data/demo/dispatch.json --export-social-media data/demo/social_media.json
```
- Twitter posts: ≤280 characters with hashtags
- Facebook posts: More detailed with full incident information
- All posts marked as "SIMULASI/SIMULATION"

### Email Notifications
Generate email templates for dispatches:
```bash
python -m c_agent.agent --data-dir data/demo --output data/demo/dispatch.json --export-email data/demo/email_summary.json
```
- Individual dispatch emails with full details
- Batch summary emails for multiple dispatches
- Bilingual subject lines and bodies

### Summary Statistics
Generate summary statistics for analysis:
```bash
python -m c_agent.agent --data-dir data/demo --output data/demo/dispatch.json --export-summary data/demo/summary.json
```
- Total dispatches by action type
- Dispatches by priority level
- Audience distribution
- Water source availability statistics

### CSV Export
Export dispatches to CSV for spreadsheet analysis:
```bash
python -m c_agent.agent --data-dir data/demo --output data/demo/dispatch.json --export-csv data/demo/dispatch.csv
```

### HTTP Server
Run a local HTTP server for frontend integration:
```bash
python -m c_agent.server --host 127.0.0.1 --port 8000
# or
python -m c_agent.run_server --host 127.0.0.1 --port 8000
```
API endpoints:
- `/api/dispatch` - Dispatch data
- `/api/summary` - Summary statistics
- `/api/risk-distribution` - Risk level distribution
- `/api/social-media` - Social media posts
- `/api/email-summary` - Email summary
- `/api/timeline` - Incident timeline

Policy summary (see `decision_rules.md`):

1. Resolve each cell to one driving horizon (highest level, then score, then shortest horizon).
2. CRITICAL → `DISPATCH` to all five audiences; CRITICAL cells within 15 km (configurable via `--cluster-distance-km`) also get `BRIEF` for leadership.
3. HIGH with falling `sm_27_81_delta_7d` → `SMS_WARN` (MPA) and `REWET` (BRGM).
4. One active incident per cell; escalate only when severity rises; default 6h cooldown.
5. Message text is templated from structured fields only.
6. Water candidates come from Role A (`a_data/mock_water_sources.json`, or `--water-sources` / `data-dir/water_sources.json`). C attaches the nearest source to each dispatch; missing catalogue → `null`. A nearest source farther than 15 km (`--max-water-km`, `0` disables) is also `null`.

   C now supports Role A's `WaterIndex` (spatial index with metric projection) when `water_sources.geojson` is available and Role A's dependencies (osmium, shapely, pyproj) are installed. Falls back to simple Haversine distance for JSON array catalogues.
7. Optional `--llm`: with `GEMINI_API_KEY` set (or `ANTHROPIC_API_KEY`; force with `LLM_PROVIDER=gemini|anthropic`; model via `AGENT_MODEL`, confirm the id in Google AI Studio), `llm.py` rephrases the templated messages. Coordinates, targets, priorities, audiences, water and all numbers stay deterministic. The rewrite is used only if it keeps the same audiences, starts with `Simulasi` / `Simulation`, adds no number absent from the facts or template, and keeps `mpa` SMS ≤160 characters; otherwise the template is used. The model is called only when a new dispatch is minted, never on a dedupe reuse. Standard library only (no SDK, nothing extra to install on LinuxONE).
8. Live mode stops with a clear message if `features.json`, `risk.json` or `cells.geojson` is missing; it never substitutes mocks.

```bash
python -m c_agent.agent --data-dir data/processed --output data/processed/dispatch.json --llm
python -m unittest discover -s c_agent/tests -v   # policy + hardening tests
```

Done when CRITICAL input creates a valid dispatch with all five messages, reruns do not duplicate active incidents, escalation is tested, and no real notification is sent.
