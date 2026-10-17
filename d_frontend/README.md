The peatland highlight now covers the supplied mapped peat polygons across all five Indonesian Kalimantan provinces, clipped to their combined administrative boundary. Rebuild with `.venv/Scripts/python.exe d_frontend/extract_peatland.py`. Polygon holes are preserved; this shows the supplied dataset extent, not a guarantee of complete contemporary peat coverage. This supersedes the Central Kalimantan mask described below.

Current dataset: the website loads 40 unique cells from `data/demo/role_a_real/regional_40/`, timestamp `2026-10-16T00:00:00Z`. No risk or dispatch files are currently supplied for this dataset; markers remain visible with unavailable predictions. Rebuild the static copy with `python -m d_frontend.export_coverage`. Start with `python -m d_frontend.serve_demo` and open http://127.0.0.1:8001. The earlier 33-cell workflows below are retained as historical documentation.

# Role D — Frontend / alerts

## Automatic live mode

Start `python -m e_platform.live_service` to view automatically refreshed live
inputs, predictions and simulated responses on port 8001. The browser checks for
new complete generations every minute, displays their feature timestamp, and
flags stale data/refresh errors. The automatic service owns the response run;
automatic refreshes start at each clock hour. **Refresh live data** requests a
complete data fetch, inference and simulated-response run immediately, with
progress feedback and protection against overlapping runs.
manual generation is disabled in this mode. It never falls back to bundled
historical data while waiting for live data. The regular `serve_demo` command
continues to serve the historical demo. See
[LIVE_OPERATIONS.md](../e_platform/LIVE_OPERATIONS.md) for setup and auto-start.

## Interface

The app uses a left navigation rail, forecast-driven status cards, a large regional
map, and separate cell-insight/response sections. Warm neutral surfaces, forest
colors, ember accents and a custom SVG landscape provide the visual theme.
SF Pro/San Francisco is preferred through Apple's system font stack and installed
SF Pro fonts, with system fallbacks elsewhere. No remote fonts or image assets
are required for the interface.

Risk counts, the three highest-scoring cells, modeled rainfall/soil averages and
the UTC snapshot time come from the selected feeds. The watchlist selects the
matching center on the map. Missing values remain unavailable. The interface
labels historical replay and synthetic data explicitly; it makes no current-fire
claims. Keyboard focus, named navigation icons, reduced-motion settings and
narrow-screen layouts are supported.

Check the status cards and watchlist with `node d_frontend/test_status.cjs`.

## Use the datasets in data/demo

The website is now fixed to the 33 spread-out cells in `data/demo/central_coverage/`.
Other datasets remain on disk but are not offered by the interface, and missing
data does not fall back to the older 9-cell or mock feeds. The top-right historical
replay badge is removed; the feature timestamp and source notes remain visible.
When the server lacks `/demo/catalog.json`, the website loads the same real data
from `assets/coverage-snapshot.json`, so the original plain static server also
shows the map and all 33 points. Regenerate this frontend copy after updating the
source bundle with `python -m d_frontend.export_coverage`. This is real-source
historical data, not a synthetic fallback.

From PowerShell at the repository root:

```powershell
python -m d_frontend.serve_demo
```

Open **http://127.0.0.1:8001**. Stop any older server on that port with Ctrl+C
before starting this one, or add `--port 8002`. This server uses only Python's
standard library; no dependency installation is needed.

The Dataset selector reads these existing directories directly, without copying
or overwriting them:

| Selection | Source | Behavior |
| --- | --- | --- |
| Central Kalimantan · 33 spread-out cells | `data/demo/central_coverage/` | Default when complete: geographically distributed real-source replay, with 99 matching predictions |
| Real-data run | `data/demo/real/` | Nine cells with matching risk and dispatch feeds |
| Real-data replay | `data/demo/role_a_replay/` | Original 33-cell replay; missing risk/dispatch feeds are explicitly unavailable |
| Synthetic demo | `data/demo/` | Three synthetic fixture cells and simulated dispatch |

The actual feature timestamps and cell counts appear below the controls. Changing
datasets loads its own features, geometry, predictions and dispatches together;
missing predictions never fall back to another dataset or a static mock. A
failed request or mismatched cell/timestamp clears the previous display and
shows an error. On a successful dataset change, the map focuses its monitored
cells. Selecting a cell shows its measurements, units and UTC timestamp; null
measurements display as unavailable. Files added by their owners become visible
after reloading the page. Peat masks and basemap behavior are unchanged.

Only the four handoff filenames per selected directory are exposed. Raw inputs,
Parquet training data, caches and other repository folders are not served.
The original `e_platform.serve` and standalone mock workflow remain supported.

Verification:

```powershell
python -m unittest d_frontend.test_serve_demo -v
node d_frontend/test_data.cjs
python -m contracts.validate
```

Read `TEAM_PLAYBOOK.md` and `contracts/CONTRACTS.md`. Own this folder. The starter uses browser-native HTML, CSS and JavaScript; no Node build is required. Choose and document your app framework / map library here when needed, preserving the static mock flow.

```bash
bash scripts/setup.sh d
source .venv/bin/activate
make demo
```

Open `http://127.0.0.1:8000`. E's local server exposes `/data/{features.json,risk.json,dispatch.json,cells.geojson}`. Each feed independently falls back to `mocks/` with a visible source label. To test without the pipeline or E's server:

```bash
python -m http.server 8001 --bind 127.0.0.1 --directory d_frontend
```

Open `http://127.0.0.1:8001`; all four feeds use bundled mocks. Opening `index.html` via `file://` is unsupported because browsers restrict JSON fetches. No CDN or external network is required for this starter. `mock_output.json` is the risk input snapshot; there is no separate frontend JSON output contract.

The current page is an integration handoff viewer with a horizon selector, risk rows and dispatch messages. Build the product next:

1. Add the peat/cell map: LOW green, MODERATE yellow, HIGH orange, CRITICAL red. GeoJSON is already `[lon, lat]`; do not swap it again. Show top factors in tooltips.
2. Add five role views: Manggala Agni target / water source / route; MPA SMS preview; BPBD map and active dispatches; BRGM deep soil moisture trend; Leadership counts and one-line brief.
3. Keep the 24/48/72-hour selector linked to map and detail views.
4. Coordinate surge simulation with B/C/E. Label injected synthetic data and simulate dispatches without sending messages. A static surge fixture must work offline.
5. Keep fallback behavior visible. A water source may be null; do not render a fabricated route. State that weather/soil inputs are modeled and thermal hotspots describe surface emergence.

Done when the full three-minute flow, including surge and all audience views, runs from static mock files. Record any new open-source dependency with E in the root README.

## Regional map

The map uses native SVG (no additional JavaScript libraries) and displays supplied
GeoJSON cells inside the Kalimantan regional bounding box: 108–119.5° E,
4.5° S–4.5° N. This is a regional viewport, not an administrative boundary mask;
neighboring land can appear. Current mock coverage remains Central Kalimantan.
Selecting a cell exposes its risk, contributing signals, and UTC timestamp.
The shared forecast selector updates the colors and detail text. Use “Focus
monitored cells” to inspect the small fixture grid; “Whole region” resets the view.

Basemap dataset: [OpenStreetMap contributors](https://www.openstreetmap.org/copyright),
using [standard raster tiles](https://tile.openstreetmap.org/) at zoom 6.
Tiles require internet access; cell geometry and selection work without tiles.
The map preserves visible attribution and does not prefetch or bulk-download tiles.
Role E should include this dataset in the root dependency/source inventory.

Map navigation: drag to pan within the regional bounds; scroll over the map to
zoom around the pointer. Zoom buttons remain available. A drag does not select a
risk cell; click or use Enter/Space to select one.

Basemap tiles now adapt to the visible zoom and screen density (up to 2×),
loading only the current viewport after navigation pauses. Previous tiles remain
visible during loading. Risk boundaries remain vector shapes, with colored
markers at regional scale and explicit risk-level/score labels when zoomed in.
Risk indicates predicted surface hotspot emergence, not confirmed burning.

## Peat-only risk shading

`assets/peatland.geojson` is a display-only extract of the bundled
`data/raw/Indonesia_Peat_Lands.geojson`, described in the team playbook as the
[Global Forest Watch Indonesian peat layer](https://www.globalforestwatch.org/).
Exact upstream layer URL, survey date, and license remain unverified in the
bundled source metadata. It is not a complete contemporary land classification.
Rebuild with `python d_frontend/extract_peatland.py` from repository root.
The extraction retains source polygon rings and holes, drops the Z coordinate,
and selects polygons intersecting the regional viewport without simplifying them.
No processed handoff data is changed. The static extract is about 10 MB.

Risk-cell fills, markers, and labels are SVG-clipped to these peat polygons.
Gray means outside the supplied mapped peat extent (not proof of absence);
pale sage means mapped peatland without a selected-horizon prediction.
No risk shading is shown if the peat dataset cannot load. Mock grid cells and
risk values remain synthetic and may not overlap the real peat polygons.


## Central Kalimantan highlight scope

The highlight mask now intersects the raw Indonesian peat polygons with the
actual Central Kalimantan province boundary (`shapeISO: ID-KT`) from the cached
geoBoundaries ADM1 file at
`data/demo/role_a_real/cache/geoBoundaries-IDN-ADM1.geojson`. This supersedes the
previous Kalimantan-wide viewport extract. Only the 122 nonempty source peat features
intersecting that province are retained, preserving holes and clipping cross-border
polygons. No rectangular bounding box is used for the mask.

Rebuild with `.venv312/Scripts/python.exe d_frontend/extract_peatland.py`
(Shapely is needed for extraction, not to serve the website). The frontend asset
is about 3 MB. Basemap tiles remain grayscale throughout the map; sage peat
shading and risk colors are restricted to this mask. Gray outside the province
means outside the selected scope, not absence of peat in other provinces.
Raw sources, model outputs, thresholds, and shared contracts are unchanged.
Boundary provenance is retained in Role A's cache/metadata and root dataset inventory.

All selected-dataset cell centers now render in a separate, unclipped marker layer.
The 33-cell replay opens by default when available. Blue centers indicate no
prediction; centers with predictions use risk colors. Markers are grid centers,
not ignition locations; click or press Enter/Space for measurements. Risk shading
remains clipped to actual Central Kalimantan peat polygons.

## Spread-out sampling with matching predictions

The original 33 replay cells were clustered because they were the locations with
completed long-term weather caches. `prepare_coverage.py` selects 33 existing
peat-intersecting grid cells across Central Kalimantan using greedy maximum-distance
sampling in a local metric projection. It preserves actual cell IDs/coordinates;
it does not move measurements or invent risk values. Candidates have at least
5% peat and centers within the province boundary. This is representative sampling,
not complete coverage of all 394 candidate cells or every peat polygon.

To rebuild from the repository root using the existing spatial/model environment:

```powershell
.venv312/Scripts/python.exe -m d_frontend.prepare_coverage --plan-only
.venv312/Scripts/python.exe -m d_frontend.prepare_coverage
# Repeat using downloaded weather only:
.venv312/Scripts/python.exe -m d_frontend.prepare_coverage --offline
```

The builder reuses A's WeatherClient (including its shared API-budget ledger),
weather parser and feature calculations, B's existing artifacts, and C's deterministic
simulated policy. It fetches 31 days of warmup around the declared historical replay
hour; it does not train or evaluate models. Source requests and spatial completeness
limits are recorded in `source_manifest.json`. A single compute thread avoids
oversubscribing OpenBLAS on a small batch. An empty water catalogue prevents
synthetic canal coordinates from being attached to the real-source replay.

The new bundle is served only after all four feeds validate and `build_status.json`
says complete. Existing replay bundles and checked-in processed/model files are
preserved. Restart `python -m d_frontend.serve_demo`, then refresh the page to see
the new default dataset and its distributed center markers.


## Response workspace

Start `.venv/Scripts/python.exe -m d_frontend.serve_demo` and open port 8001.
The Response log navigation opens the incident workspace: search/action/audience
filters, targets and water sources, bilingual audience/SMS previews, social posts,
individual and batch email previews, JSON/CSV downloads, response statistics and
UTC timeline. Policy & engine includes cooldown, water radius, optional guarded
LLM rephrasing and a simulated notification log. Keys stay server-side.

Generate simulated responses invokes C against the matching regional_40 inputs,
validates them, writes C's dispatch.json in that dataset, and persists state/logs
under c_agent/state and c_agent/logs. No external notification is sent. Restart
older demo servers to enable the new endpoints. Static hosting supports saved
incidents and local dispatch/CSV/summary/timeline downloads; simulation and generated
social/email previews require the local server. Run the standard snapshot exporter
after generation to update standalone static copies.

Verification: `.venv/Scripts/python.exe -m unittest d_frontend.test_response_api d_frontend.test_serve_demo -v`.


Click any monitoring marker (or focus it and press Enter/Space) to open its floating
model explanation. It includes the selected-horizon risk probability and fixed
classification thresholds, supplied top factors with signed relative-magnitude
bars, matching raw inputs/units, model version, and UTC snapshot. Expand the input
list to inspect all 27 canonical measurements. These are supplied heuristic factors,
not causal effects or exact calibrated-probability decompositions. Missing predictions
and null measurements remain explicitly unavailable. Close with Escape or the close
button; changing the forecast horizon updates an open explanation.


## Historical data analytics page

Open `analytics.html` (or choose **Data analytics** in the sidebar). This separate
page contains no model predictions. It lists all 40 points with province search,
sorting and full-history temperature/moisture averages. Selecting a point loads
its daily measurements: interactive chart, date filters, 90-day/year shortcuts,
chart hover tooltip with keyboard and touch support, paginated historical table, all measurement fields,
and CSV exports. Every date and aggregation uses UTC.

The source is A's unchanged `regional_40/history.parquet`: 656,640 hourly rows from
2024-12-02 through 2026-10-16, exported to 40 lazily loaded frontend JSON assets.
Regenerate after source updates with:

```powershell
.venv312/Scripts/python.exe -m d_frontend.analytics_data
```

The exporter reads only input measurements; it excludes risk feeds, model artifacts
and target labels. Daily means use available samples; daily rain/ET totals require
24 valid hours; rolling counts use daily maxima and must not be summed as unique
fires. Rolling rainfall/derived summaries take the final hourly record. Wind
directions use a circular mean. The inspector and CSV preserve valid-hour counts
and missing values. Both the demo server and plain static hosting serve this page.
The abandoned prediction-archive endpoint and artifacts were removed.

Checks: `.venv312/Scripts/python.exe -m unittest d_frontend.test_analytics -v`
and `node d_frontend/test_analytics.cjs`.


Analytics now opens with a location-only list: cell ID, province, coordinates and
peat coverage. Historical measurements are neither fetched nor displayed until
a point is selected. The selected-point view includes an All monitoring points
back button; returning hides historical details. Refresh resets to the list.

Both pages share the Home/Analytics sidebar and `navigation.js` interactions, including hover descriptions, active-page state, sidebar toggle and animated flame.

Analytics chart tooltips replace the Inspect a day slider. Hover/tap to inspect the orange marker; arrow keys move between days while the chart is focused, and Escape dismisses the tooltip.


The response workspace uses the shared real OSM water catalogue for regional_40.
Start with `.venv/Scripts/python.exe -m d_frontend.serve_demo` for spatial lookup.
Mapped candidates do not establish current availability, operational suitability
or field access. Catalogue and radius changes regenerate saved incident content.


## Forest rescue Easter egg

Activate the sidebar flame **five times** (mouse/touch, or Enter/Space while its
button is focused; no more than two seconds between activations). Home and Analytics
open the same isolated mini-game from `easter_egg.html`. Turn the valve on, drag the
hose toward the tree, or use the labeled Hose aim control with keyboard arrows.
Keep water on target to finish; Play Again resets it. Escape or Close returns to
the page and restores focus to the flame. The game has reduced-motion styling,
touch input, one timer, and unloads when closed. It never changes measurements,
predictions or dispatches. The brand text remains the Home link.

Browser checks covered the unlock threshold, valve pause/resume, winning, replay,
Escape, focus restoration, both pages and a 390px mobile viewport.

Analytics now also displays a latest-risk badge for each point and in its detail header. It uses the highest supplied 24/48/72-hour forecast at that point's latest timestamp. The timestamp is displayed separately from historical measurement dates; missing forecasts show Unavailable, never LOW. No historical risk is inferred.
