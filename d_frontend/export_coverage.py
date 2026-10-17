"""Package the existing 33-cell snapshot for plain static frontend servers."""
import json
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    source = root / 'data/demo/central_coverage'
    names = ['features.json', 'cells.geojson', 'risk.json', 'dispatch.json']
    feeds = {name: json.loads((source / name).read_text(encoding='utf-8')) for name in names}
    features = {row['cell_id']: row['ts'] for row in feeds['features.json']}
    cells = {row['properties']['cell_id'] for row in feeds['cells.geojson']['features']}
    if len(cells) != 33 or cells != set(features):
        raise ValueError('Snapshot must contain exactly 33 matching feature and geometry cells')
    if len(feeds['risk.json']) != 99 or any(features.get(row['cell_id']) != row['ts'] for row in feeds['risk.json']):
        raise ValueError('Expected 99 predictions matching the feature snapshot')
    target = root / 'd_frontend/assets/coverage-snapshot.json'
    payload = {'id': 'coverage', 'label': 'Central Kalimantan · 33 spread-out cells',
               'description': 'Bundled real-source historical snapshot. Representative samples, not complete coverage; model evaluation is unverified.',
               'source': 'data/demo/central_coverage', 'files': names, 'feeds': feeds}
    temporary = target.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(',', ':')), encoding='utf-8')
    temporary.replace(target)
    print('Exported real 33-cell snapshot with 99 matching predictions')


if __name__ == '__main__':
    main()
