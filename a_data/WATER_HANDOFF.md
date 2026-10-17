# Role A water-source mock for Role C

This bundle supplies three synthetic candidate water points near our existing Central Kalimantan mock cells, plus five expected lookup examples. Every source and example is explicitly marked `is_mock: true`. Coordinates and water features are invented for integration. Water presence, access, intermittency, and seasonality are unknown and remain `null`.

The raw file `data/raw/kalimantan-261016.osm.pbf` is present with an OSM header. Its Git LFS tracking rule is already configured. These mocks have not been extracted from that file. Real water-feature extraction is the next data-processing step.

## Files

| File | Purpose |
| --- | --- |
| [mock_water_sources.json](mock_water_sources.json) | Array of three candidate source points: a canal, river, and pond. |
| [fixtures/water_lookup_examples.json](fixtures/water_lookup_examples.json) | Expected nearest-source results for three cell centers, a changed incident target, and an empty candidate list. |
| [mock_output.json](mock_output.json) | Existing feature mock with the matching cell IDs and snapshot time. |

The catalogue and example wrappers are supporting fixture layouts for A/C integration. Their metadata belongs outside the frozen dispatch `water_source` object. Role C should confirm the production catalogue layout before wiring real source extraction into its policy.

The existing `a_data.refresh --mock` command exports the feature and cell-geometry pair. The water catalogue and lookup examples are provided separately at the paths above for Role C to load.

## Candidate catalogue

Each source has `source_id`, `name`, named `lat`/`lon`, and `kind`. It also has `is_mock`, `osm_id`, `water_available`, `access`, `intermittent`, and `seasonal`. `source_id` identifies the candidate within this bundle. `osm_id` is null because no real OSM object is being represented.

Candidate records have no fixed distance. Distance depends on the incident target and must be calculated at lookup time. These are synthetic point candidates; real rivers and lakes will require their actual geometry or mapped intake/shoreline points.

## Expected lookup results

Distances are straight-line spherical Haversine distances using mean Earth radius 6371.0088 km, rounded to three decimals. They are distances between synthetic coordinates, rather than travel distances or verified access routes. Each nonempty example searches all three candidates.

| Scenario | Lookup target (lat, lon) | Expected candidate | Distance (km) |
| --- | --- | --- | --- |
| Cell `-2.35_114.05` | `-2.35, 114.05` | `mock_canal_001` | 4.007 |
| Cell `-2.45_114.15` | `-2.45, 114.15` | `mock_river_001` | 3.144 |
| Cell `-2.55_114.25` | `-2.55, 114.25` | `mock_pond_001` | 2.484 |
| Changed incident target associated with the first cell | `-2.42, 114.12` | `mock_river_001` | 1.572 |
| Empty candidate input for the third cell | `-2.55, 114.25` | `null` | `null` |

The changed-target case demonstrates that the lookup must use the dispatch's actual `target`. Reusing a precomputed result by `cell_id` alone would select the wrong source in that example. The empty-input example represents no supplied candidates; it makes no claim about real-world water coverage.

Each example includes `case_id`, `is_mock`, `cell_id`, `ts`, `target`, `candidate_source_ids`, `expected_source_id`, and `water_source`. Example timestamps are the fixed UTC mock snapshot `2026-10-17T09:00:00Z`. Cases are identified by `case_id`; these examples are not a features or dispatch feed.

## Role C integration

1. Load the catalogue as a JSON array. Use the IDs in an example to select its candidate inputs; use the catalogue directly for an ordinary mock lookup.
2. Calculate distance from the actual incident target to each supplied candidate. Choose the nearest candidate before rounding the output distance.
3. Produce a `water_source` containing exactly `lat`, `lon`, `distance_km`, and `kind`. For an empty candidate set, use `water_source: null`.
4. Keep source IDs and quality/provenance metadata in supporting data. The four-field object can be embedded in a schema 1.0 dispatch record.

For the first example, the dispatch field is:

```json
{
  "water_source": {
    "lat": -2.33,
    "lon": 114.02,
    "distance_km": 4.007,
    "kind": "canal"
  }
}
```

The catalogue does not establish source suitability or a maximum operating distance. Role C owns those selection rules. Current Role C policy still emits `water_source: null`; connecting this supporting fixture to that policy belongs to its engineer. Alerts remain simulated.

## Real-data source and follow-up

The planned source is the [Geofabrik Kalimantan OpenStreetMap extract](https://download.geofabrik.de/asia/indonesia/kalimantan.html), credited to OpenStreetMap contributors and distributed under ODbL. When producing real data, record the exact file/version, extract timestamp, licence, filtering rules, and original OSM identifiers. Coordinate root dataset attribution with Role E.

Extract candidate rivers, canals, ponds, reservoirs, and mapped firefighting water points around the selected peat cells. Preserve available access, seasonal, and intermittent tags, check geometry, and agree the real geometry handoff with C. Record unknown water availability explicitly.

## Message to Role C

> Role A's water mock is ready at `a_data/mock_water_sources.json`. It contains three explicitly synthetic canal/river/pond points with unknown availability and access represented as nulls. `a_data/fixtures/water_lookup_examples.json` contains five expected lookup cases, including a shifted incident target and an empty input returning `water_source: null`. Each non-null `water_source` uses the existing schema 1.0 four-field shape. See `a_data/WATER_HANDOFF.md` for distance definitions and integration details. Real extraction from the downloaded PBF is pending.
