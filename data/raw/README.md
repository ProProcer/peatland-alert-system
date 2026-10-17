# Raw sources and cache — Role A

The following source files are tracked so the team can use the same inputs:

- `Indonesia_Peat_Lands.geojson` — Indonesian peatland polygons.
- `DL_FIRE_J1V-C2_824564.zip` — FIRMS archive and NRT CSV files for J1V-C2.
- `DL_FIRE_J2V-C2_824565.zip` — FIRMS archive and NRT CSV files for J2V-C2.

Other downloads, extracted CSVs, per-location Open-Meteo caches and Windows `Zone.Identifier` metadata remain ignored by Git. Keep small, synthetic fixtures in `a_data/fixtures/` instead. The bundled sources are excluded from the offline demo's Docker build context.

Record the exact source URL, license, query bounding box, UTC download time, time range, units and whether data is modeled. Keep API credentials out of files and source-control history. Do not assume the playbook's Berlin / Kenya format samples belong to the Indonesian demo.
