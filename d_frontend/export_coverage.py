"""Package the prepared 40-cell dataset for plain static frontend servers."""
import json
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    source = root / 'data/demo/role_a_real/regional_40'
    names = ['features.json', 'cells.geojson', 'risk.json', 'dispatch.json']
    available = [name for name in names if (source / name).is_file()]
    feeds = {name: json.loads((source / name).read_text(encoding='utf-8')) if name in available else [] for name in names}
    features = {row['cell_id']: row['ts'] for row in feeds['features.json']}
    cells = {row['properties']['cell_id'] for row in feeds['cells.geojson']['features']}
    if len(cells) != 40 or cells != set(features) or len(feeds['features.json']) != 40:
        raise ValueError('Snapshot must contain exactly 40 unique matching feature and geometry cells')
    if any(features.get(row['cell_id']) != row['ts'] for row in feeds['risk.json']):
        raise ValueError('Predictions must match the feature snapshot')
    target = root / 'd_frontend/assets/coverage-snapshot.json'
    payload = {'id': 'coverage', 'label': 'Kalimantan ? 40 cells',
               'description': 'Real-source historical snapshot. Predictions and dispatches are unavailable unless supplied for this dataset.',
               'source': 'data/demo/role_a_real/regional_40', 'files': available, 'feeds': feeds}
    temporary = target.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(',', ':')), encoding='utf-8')
    temporary.replace(target)
    print(f"Exported real {len(cells)}-cell snapshot with {len(feeds['risk.json'])} supplied predictions")


if __name__ == '__main__':
    main()
