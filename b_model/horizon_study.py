"""Research-only horizon sensitivity with common rows, settings and full purges."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import time

import joblib
import numpy as np
from omegaconf import OmegaConf
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.metrics import balanced_accuracy_score

from b_model.config import FEATURE_COLUMNS, HORIZONS, PROJECT_ROOT
from b_model.experiment import calibrate, fit_model, probability_metrics, utc, write_json


def future_labels(frame, events, horizons, coverage):
    """Reproduce A's (t,t+h] n/h labels; unknown coverage stays null."""
    if coverage['status'] != 'human_declared_complete_local_J1V_J2V_exports':
        raise ValueError('Future negatives require declared source coverage')
    if not horizons or any(isinstance(h, bool) or not isinstance(h, int) or h < 1 for h in horizons):
        raise ValueError('Positive integer horizons required')
    times = pd.DatetimeIndex(pd.to_datetime(frame.ts, utc=True)).as_unit('ns').asi8
    eligible = events.loc[events.alert_eligible & events.in_scope].copy()
    eligible['_ns'] = pd.DatetimeIndex(pd.to_datetime(eligible.ts, utc=True)).as_unit('ns').asi8
    grouped = {cell: np.sort(g._ns.to_numpy()) for cell, g in eligible.groupby('cell_id')}
    start, end = utc(coverage['start']).value, utc(coverage['end_exclusive']).value
    result = frame[['cell_id', 'ts']].copy()
    for h in horizons:
        future = times + h * 3_600_000_000_000
        observed = (times >= start) & (future < end)
        values = np.zeros(len(frame), dtype=np.int8)
        for cell, indices in frame.groupby('cell_id', sort=False).indices.items():
            detections = grouped.get(cell, np.array([], dtype=np.int64))
            values[indices] = (np.searchsorted(detections, future[indices], side='right') >
                               np.searchsorted(detections, times[indices], side='right')).astype(np.int8)
        result[f'target_{h}h'] = pd.array(np.where(observed, values, np.nan), dtype='Int8')
    return result


def study_parts(frame, validation_start, validation_end, max_horizon, calibration_days):
    """Identical boundaries for every horizon, purged by the longest target."""
    if max_horizon < 1 or calibration_days < 1:
        raise ValueError('Positive purge and calibration duration required')
    vs, ve = utc(validation_start), utc(validation_end)
    ce = vs - pd.Timedelta(hours=max_horizon)
    cs = ce - pd.Timedelta(days=calibration_days)
    te = cs - pd.Timedelta(hours=max_horizon)
    t = frame['_time']
    parts = {'train': frame.loc[t < te], 'calibration': frame.loc[(t >= cs) & (t < ce)],
             'validation': frame.loc[(t >= vs) & (t < ve)]}
    if not vs < ve or any(part.empty for part in parts.values()):
        raise ValueError('Nonempty chronological partitions required')
    return parts


def metrics(y, scores, cutoff):
    result = probability_metrics(y, scores)
    y = np.asarray(y, dtype=int)
    both = len(np.unique(y)) == 2
    result.update(accuracy=float(np.mean((np.asarray(scores) >= cutoff) == y)),
        balanced_accuracy=float(balanced_accuracy_score(y, np.asarray(scores) >= cutoff)) if both else None,
        always_hotspot_accuracy=float(y.mean()), always_no_hotspot_accuracy=float(1 - y.mean()),
        accuracy_above_best_constant=float(np.mean((np.asarray(scores) >= cutoff) == y) - max(y.mean(), 1-y.mean())))
    return result


def run(plan):
    horizons = plan['horizons_h']
    if sorted(set(horizons)) != horizons or not set(HORIZONS).issubset(horizons):
        raise ValueError('Use sorted unique research horizons including the contracted horizons')
    output, evidence = [PROJECT_ROOT / plan[k] for k in ('output_dir', 'evidence_dir')]
    if output.exists() or evidence.exists():
        raise FileExistsError('Use fresh run/evidence directories')
    source, event_path = [PROJECT_ROOT / plan[k] for k in ('history', 'events')]
    coverage = json.loads((PROJECT_ROOT / plan['coverage_config']).read_text())['firms_export_coverage']
    frame = pd.read_parquet(source)
    if frame.duplicated(['cell_id', 'ts']).any() or not frame.ts.str.endswith('Z').all():
        raise ValueError('Unique UTC cell/hour keys required')
    values = frame[FEATURE_COLUMNS].to_numpy(dtype=float)
    if np.isinf(values).any() or (values == -999).any():
        raise ValueError('Invalid predictor values')
    labels = future_labels(frame, pd.read_parquet(event_path), horizons, coverage)
    for h in HORIZONS:
        old, new = frame[f'target_{h}h'], labels[f'target_{h}h']
        if not old.isna().equals(new.isna()) or not old.dropna().eq(new.dropna()).all():
            raise ValueError(f'Raw-event labels disagree with A for {h}h; stop for producer review')
    for h in horizons:
        frame[f'target_{h}h'] = labels[f'target_{h}h']
    targets = [f'target_{h}h' for h in horizons]
    complete = frame.dropna(subset=targets).sort_values(['ts', 'cell_id']).copy()
    complete['_time'] = pd.to_datetime(complete.ts, utc=True)
    assert all((complete[targets[i]] <= complete[targets[i+1]]).all() for i in range(len(targets)-1))
    for directory in (output, evidence):
        directory.mkdir(parents=True)
        OmegaConf.save(OmegaConf.create(plan), directory / 'protocol.yaml')
    labels.to_parquet(output / 'research_labels.parquet', index=False)
    metadata = {'status': 'Retrospective research; no model selection, promotion or shared contract changes.',
        'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
        'events_sha256': hashlib.sha256(event_path.read_bytes()).hexdigest(),
        'coverage': coverage, 'original_labels_exact_match': HORIZONS,
        'source_rows': len(frame), 'common_complete_rows': len(complete), 'excluded_incomplete_rows': len(frame)-len(complete),
        'latest_common_timestamp': complete.ts.max(), 'model': '27-feature balanced Logistic Regression, C=0.001, sigmoid calibration',
        'baseline_note': 'Always-hotspot/no-hotspot accuracies describe constants on evaluation labels, not tuned deployed classifiers.',
        'comparison_note': 'All horizons retrained with identical source rows, features, C and 336h purges. Not directly comparable with the prior 72h-purge evaluation.'}
    write_json(evidence / 'metadata.json', metadata)
    windows = OmegaConf.to_container(OmegaConf.load(PROJECT_ROOT / plan['reference_windows']))['windows']
    results, csv = [], []
    begin = time.perf_counter()
    for window in windows:
        parts = study_parts(complete, window['validation_start'], window['validation_end'], max(horizons), plan['calibration_days'])
        audit = {k: {'rows': len(p), 'start': p.ts.min(), 'end': p.ts.max(),
            'positive_rows': {str(h): int(p[f'target_{h}h'].sum()) for h in horizons}} for k,p in parts.items()}
        write_json(evidence / f"split_{window['name']}.json", audit)
        if parts['train'][FEATURE_COLUMNS].isna().all().any():
            raise ValueError('A training predictor is entirely missing')
        imputer = SimpleImputer(strategy='median').fit(parts['train'][FEATURE_COLUMNS])
        X = {k: imputer.transform(p[FEATURE_COLUMNS]) for k,p in parts.items()}
        for h in horizons:
            y = {k: p[f'target_{h}h'].to_numpy(dtype=int) for k,p in parts.items()}
            if any(len(np.unique(y[k])) < 2 for k in ('train','calibration')):
                results.append({'window':window['name'],'horizon_h':h,'status':'not_estimable_single_class_fit_partition'})
                continue
            base = fit_model({'backend':'logistic_regression','c':plan['logistic_c']},plan['seed'],X['train'],y['train'])
            model = calibrate(base,X['calibration'],y['calibration'],h,'sigmoid')
            scores = model.predict_proba(X['validation'])[:,1]
            val = parts['validation']
            quiet = val.hotspots_in_cell_24h.eq(0).fillna(False).to_numpy(dtype=bool)
            result = {'window':window['name'],'horizon_h':h,'status':'evaluated',
                'metrics':metrics(y['validation'],scores,plan['classification_cutoff']),
                'quiet_metrics':metrics(y['validation'][quiet],scores[quiet],plan['classification_cutoff']) if quiet.any() else None}
            results.append(result)
            csv.append({'window':window['name'],'horizon_h':h,**{k:v for k,v in result['metrics'].items() if not isinstance(v,(dict,list))}})
            stem = f"{window['name']}_{h}h"
            joblib.dump({'model':model,'imputer':imputer,'feature_columns':FEATURE_COLUMNS},output/f'{stem}.joblib')
            pred = val[['cell_id','ts']].copy();pred['label'],pred['score']=y['validation'],scores
            pred.to_parquet(output/f'{stem}_predictions.parquet',index=False)
            write_json(evidence/'results.json',results)
            print(stem, 'accuracy=',round(result['metrics']['accuracy'],4), 'always_yes=',round(result['metrics']['positive_rate'],4),flush=True)
    write_json(evidence/'results.json',results)
    pd.DataFrame(csv).to_csv(evidence/'summary.csv',index=False)
    metadata['runtime_seconds']=time.perf_counter()-begin
    metadata['completed_models']=len(csv)
    assert hashlib.sha256(source.read_bytes()).hexdigest()==metadata['source_sha256']
    assert hashlib.sha256(event_path.read_bytes()).hexdigest()==metadata['events_sha256']
    write_json(evidence/'metadata.json',metadata)


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,default=PROJECT_ROOT/'b_model/conf/horizon_study.yaml')
    run(OmegaConf.to_container(OmegaConf.load(parser.parse_args().config),resolve=True))
