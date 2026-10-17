"""Clip raw peatland to the cached five Indonesian Kalimantan province boundaries.

Run from repository root with Shapely installed. No boundary simplification.
"""
import json
from pathlib import Path
from shapely import force_2d, make_valid
from shapely.ops import unary_union
from shapely.geometry import MultiPolygon, mapping, shape

source = Path('data/raw/Indonesia_Peat_Lands.geojson')
target = Path('d_frontend/assets/peatland.geojson')
boundary_source = Path('data/demo/role_a_real/cache/geoBoundaries-IDN-ADM1.geojson')
boundaries = json.loads(boundary_source.read_text(encoding='utf-8'))
province_codes = {'ID-KT', 'ID-KS', 'ID-KB', 'ID-KI', 'ID-KU'}
provinces = [f for f in boundaries['features'] if f['properties'].get('shapeISO') in province_codes]
if len(provinces) != 5:
    raise ValueError('Expected all five Indonesian Kalimantan province boundaries')
region = unary_union([make_valid(force_2d(shape(f['geometry']))) for f in provinces])

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
target.write_text(json.dumps({'type': 'FeatureCollection', 'scope': 'Indonesian Kalimantan',
                             'scope_boundary': mapping(region),
                             'boundary_source': str(boundary_source), 'features': features}, separators=(',', ':')), encoding='utf-8')
print(f'Extracted {len(features)} Kalimantan peat features; {target.stat().st_size:,} bytes')
