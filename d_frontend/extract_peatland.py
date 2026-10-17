"""Clip raw peatland to the cached Central Kalimantan province boundary.

Run from repository root with Shapely installed. No boundary simplification.
"""
import json
from pathlib import Path
from shapely import force_2d, make_valid
from shapely.geometry import MultiPolygon, mapping, shape

source = Path('data/raw/Indonesia_Peat_Lands.geojson')
target = Path('d_frontend/assets/peatland.geojson')
boundary_source = Path('data/demo/role_a_real/cache/geoBoundaries-IDN-ADM1.geojson')
boundaries = json.loads(boundary_source.read_text(encoding='utf-8'))
province = [f for f in boundaries['features'] if f['properties'].get('shapeISO') == 'ID-KT']
if len(province) != 1:
    raise ValueError('Expected one Central Kalimantan (ID-KT) province boundary')
region = make_valid(force_2d(shape(province[0]['geometry'])))

def polygons(geometry):
    if geometry.is_empty or geometry.area == 0:
        return []
    if geometry.geom_type == 'Polygon':
        return [geometry]
    if hasattr(geometry, 'geoms'):
        return [polygon for part in geometry.geoms for polygon in polygons(part)]
    return []

features = []
for feature in json.loads(source.read_text(encoding='utf-8'))['features']:
    geometry = force_2d(shape(feature['geometry']))
    if not geometry.envelope.intersects(region.envelope):
        continue
    kept = polygons(make_valid(geometry).intersection(region))
    if kept:
        features.append({'type': 'Feature', 'properties': {'source_id': feature['properties'].get('globalid')},
                         'geometry': mapping(MultiPolygon(kept))})
target.parent.mkdir(parents=True, exist_ok=True)
target.write_text(json.dumps({'type': 'FeatureCollection', 'scope': 'Central Kalimantan',
                             'scope_boundary': mapping(region),
                             'boundary_source': str(boundary_source), 'features': features}, separators=(',', ':')), encoding='utf-8')
print(f'Extracted {len(features)} Central Kalimantan peat features; {target.stat().st_size:,} bytes')
