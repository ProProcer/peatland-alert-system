# Raw sources and cache — Role A

The following source files are tracked so the team can use the same inputs:

- `Indonesia_Peat_Lands.geojson` — Indonesian peatland polygons.
- `DL_FIRE_J1V-C2_824564/` — extracted FIRMS archive and NRT CSV files for J1V-C2, stored with Git LFS.
- `DL_FIRE_J2V-C2_824565/` — extracted FIRMS archive and NRT CSV files for J2V-C2, stored with Git LFS.
- `open-meteo_api.md` — saved forecast and historical request templates.

Raw CSV and `.osm.pbf` files are tracked with [Git LFS](https://git-lfs.com/) through the root `.gitattributes`. One FIRMS CSV exceeds GitHub's regular Git file limit. After cloning or pulling this repository, run the following from the repository root to retrieve the actual source files:

```bash
git lfs install --local
git lfs pull
```

`git lfs ls-files` lists the source files managed by LFS. The CSVs in the working folder should contain actual rows, rather than the small LFS pointer records stored in Git. Add new downloads and caches deliberately, and keep small synthetic fixtures in `a_data/fixtures/`. The bundled sources are excluded from the offline demo's Docker build context.

Record the exact source URL, license, query bounding box, UTC download time, time range, units and whether data is modeled. Keep API credentials out of files and source-control history. Do not assume the playbook's Berlin / Kenya format samples belong to the Indonesian demo.
