"""Extract the bundled peat polygons for the frontend's Kalimantan viewport.

Run from repository root. No simplification: retain source rings and holes.
"""
import json
from pathlib import Path

source = Path('data/raw/Indonesia_Peat_Lands.geojson')
target = Path('d_frontend/assets/peatland.geojson')
features = []
for feature in json.loads(source.read_text(encoding='utf-8'))['features']:
    geometry = feature['geometry']
    polygons = geometry['coordinates'] if geometry['type'] == 'MultiPolygon' else [geometry['coordinates']]
    kept = []
    for polygon in polygons:
        ring = polygon[0]
        xs, ys = [p[0] for p in ring], [p[1] for p in ring]
        if max(xs) < 108 or min(xs) > 119.5 or max(ys) < -4.5 or min(ys) > 4.5:
            continue
        kept.append([[[p[0], p[1]] for p in ring] for ring in polygon])
    if kept:
        features.append({'type': 'Feature', 'properties': {'source_id': feature['properties'].get('globalid')}, 'geometry': {'type': 'MultiPolygon', 'coordinates': kept}})
target.write_text(json.dumps({'type': 'FeatureCollection', 'features': features}, separators=(',', ':')), encoding='utf-8')
print(f'Extracted {len(features)} features; {target.stat().st_size:,} bytes')
