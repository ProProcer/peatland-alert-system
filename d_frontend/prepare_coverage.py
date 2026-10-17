"""Build a spread-out 33-cell display bundle using the existing A/B/C producers.

No source coordinates are moved. Writes only a new data/demo/central_coverage bundle.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
# This small inference batch does not need a thread per CPU core.
for name in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[name] = '1'


def select_spread(cells, count=33):
    """Greedy maximum-distance sample in a metric projection; deterministic ties."""
    import numpy as np
    from pyproj import Transformer
    cells = cells.sort_values('cell_id').reset_index(drop=True)
    if len(cells) < count:
        raise ValueError(f'Only {len(cells)} qualifying cells; cannot select {count}')
    project = Transformer.from_crs('EPSG:4326', '+proj=laea +lat_0=0 +lon_0=114 +datum=WGS84 +units=m', always_xy=True)
    x, y = project.transform(cells['lon'].to_numpy(), cells['lat'].to_numpy())
    points = np.column_stack([x, y])
    # Start with the highest peat-area cell, then fill the largest spatial gaps.
    selected = [int(cells['peat_area_km2'].to_numpy().argmax())]
    distances = np.full(len(cells), np.inf)
    while True:
        distances = np.minimum(distances, ((points - points[selected[-1]]) ** 2).sum(axis=1))
        distances[selected] = -1
        if len(selected) == count:
            break
        selected.append(int(distances.argmax()))
    return cells.iloc[selected].sort_values('cell_id').reset_index(drop=True), float(np.sqrt(max(0, distances.max())) / 1000)


def main():
    import pandas as pd
    import shapely
    from shapely.geometry import Point, shape
    from shapely.ops import transform, unary_union
    from a_data.common import write_json, write_parquet, utc_now, sha256
    from a_data.weather import WeatherClient, parse_response
    from a_data.assemble import build_cell, as_json_record
    from a_data.geography import TO_AREA
    from contracts.validate import validate_payload, validate_directory

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan-only', action='store_true')
    parser.add_argument('--offline', action='store_true')
    args = parser.parse_args()
    source = ROOT / 'data/demo/role_a_real'
    target = ROOT / 'data/demo/central_coverage'
    config = json.loads((ROOT / 'a_data/processing_config.json').read_text(encoding='utf-8'))
    boundaries = json.loads((source / 'cache/kalimantan_boundary.geojson').read_text(encoding='utf-8'))
    central = unary_union([shape(f['geometry']) for f in boundaries['features'] if f['properties'].get('shapeISO') == 'ID-KT'])
    cells = pd.read_parquet(source / 'cells.parquet')
    candidates = cells[(cells['province'] == 'Central Kalimantan') & (cells['peat_fraction'] >= .05)].copy()
    candidates = candidates[[central.covers(Point(row.lon, row.lat)) for row in candidates.itertuples()]]
    selected, radius = select_spread(candidates)
    report = {'generated_at': utc_now(), 'mode': 'historical_replay', 'is_mock': False,
              'selection': 'greedy maximum-distance sample of qualifying grid cells; no coordinates relocated',
              'candidate_count': len(candidates), 'cell_count': len(selected), 'snapshot': config['replay_snapshot'],
              'cell_ids': selected['cell_id'].tolist(), 'max_candidate_distance_to_sample_km': radius,
              'lon_range': [float(selected.lon.min()), float(selected.lon.max())],
              'lat_range': [float(selected.lat.min()), float(selected.lat.max())],
              'limitations': ['33 samples do not cover every peat polygon or grid cell.',
                             'Weather/soil are modeled. Existing model evaluation is unverified.',
                             'Historical replay, not current fire monitoring. Notifications are simulated.']}
    print(json.dumps(report, indent=2), flush=True)
    if args.plan_only:
        return
    target.mkdir(parents=True, exist_ok=True)
    write_json(target / 'build_status.json', {'state': 'running'})
    try:
        snapshot = pd.Timestamp(config['replay_snapshot'])
        start = (snapshot - pd.Timedelta(days=31)).strftime('%Y-%m-%d')
        end = snapshot.strftime('%Y-%m-%d')
        # Reuse the shared ledger so this run respects earlier API consumption.
        client = WeatherClient(source / 'cache/weather', daily_budget=config['weather_daily_budget'])
        weather, weather_sources = {}, []
        for i, cell in enumerate(selected.to_dict('records'), 1):
            print(f'Weather {i}/33: {cell["cell_id"]}', flush=True)
            cached = client.fetch(cell, start, end, cache_only=args.offline)
            frame, quality = parse_response(cached, cell)
            weather[cell['cell_id']] = frame
            weather_sources.append({'cell_id': cell['cell_id'], 'retrieved_at': cached['retrieved_at'], 'request': cached['request'], 'quality': quality})
        events = pd.read_parquet(source / 'firms_normalized.parquet')
        events = events[events.alert_eligible].copy()
        events['time_ns'] = pd.to_datetime(events.ts, utc=True).astype('int64')
        # build_cell uses nanoseconds even on pandas versions that default to microseconds.
        events['time_ns'] = pd.DatetimeIndex(pd.to_datetime(events.ts, utc=True)).as_unit('ns').asi8
        events = events.sort_values('time_ns').reset_index(drop=True)
        region_metric = transform(TO_AREA, unary_union([shape(f['geometry']) for f in boundaries['features']]))
        shapely.prepare(region_metric)
        rows, frames, coverage = [], [], []
        for cell in selected.to_dict('records'):
            frame, spatial = build_cell(cell, weather[cell['cell_id']], events, config, region_metric)
            frame = frame[frame.ts == config['replay_snapshot']]
            if len(frame) != 1:
                raise ValueError(f'Missing exact snapshot for {cell["cell_id"]}')
            rows.append(as_json_record(frame.iloc[0].to_dict(), cell['polygon_ids']))
            frames.append(frame.drop(columns=[f'target_{h}h' for h in (24, 48, 72)]))
            coverage.append(spatial)
        geometry = json.loads((source / 'cells.geojson').read_text(encoding='utf-8'))
        ids = set(selected.cell_id)
        geometry['features'] = [f for f in geometry['features'] if f['properties']['cell_id'] in ids]
        validate_payload('features', rows)
        validate_payload('cells', geometry)
        write_json(target / 'features.json', rows)
        write_json(target / 'cells.geojson', geometry)
        write_parquet(pd.concat(frames, ignore_index=True), target / 'features.parquet')
        report.update(weather=weather_sources, spatial_coverage=coverage,
                      grid_sha256=sha256(source / 'cells.geojson'), firms_sha256=sha256(source / 'firms_normalized.parquet'))
        write_json(target / 'source_manifest.json', report)
        del events
        weather.clear()
        import gc
        gc.collect()
        print('Generating matching predictions using existing B artifacts (no training)', flush=True)
        from b_model.predict import run_predictions
        run_predictions(features_path=target / 'features.json', output_path=target / 'risk.json', history_path=None)
        # An explicit empty catalogue prevents synthetic water sources entering a real replay.
        write_json(target / 'water_sources.json', [])
        subprocess.run([sys.executable, '-m', 'c_agent.agent', '--data-dir', str(target), '--output', str(target / 'dispatch.json'),
                        '--state-path', str(target / 'agent_state.json'), '--log-path', str(target / 'notifications.log'),
                        '--water-sources', str(target / 'water_sources.json')], cwd=ROOT, check=True)
        validate_directory(target)
        write_json(target / 'build_status.json', {'state': 'complete', 'completed_at': utc_now()})
        print(f'Complete: {target}', flush=True)
    except BaseException:
        write_json(target / 'build_status.json', {'state': 'failed'})
        raise


if __name__ == '__main__':
    main()
