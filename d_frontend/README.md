# Role D — Frontend / alerts

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
