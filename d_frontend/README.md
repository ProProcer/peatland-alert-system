# Role D — Frontend / alerts

## Use the datasets in data/demo

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
| Real-data run | `data/demo/real/` | Default: nine cells with matching risk and dispatch feeds |
| Real-data replay | `data/demo/role_a_replay/` | 33 real-data cells; missing risk/dispatch feeds are explicitly unavailable |
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
