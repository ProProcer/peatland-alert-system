"""Package the frozen regional backtest selection into a scoped B handoff.

Reads fitted models; never selects using final scores or edits another role's feeds.
"""
import argparse
import hashlib
import json
from pathlib import Path

import joblib
import numpy as np
from omegaconf import OmegaConf
import pandas as pd
from sklearn.preprocessing import StandardScaler

from b_model.config import FEATURE_COLUMNS, HORIZONS, PROJECT_ROOT
from b_model.experiment import export_bundle, load_history, split_window, write_json
from b_model.leading_indicators import ENGINEERED_FEATURES, PIPELINE_VERSION, add_leading_indicators
from b_model.quality import assess_saved_metrics
from b_model.train import compute_directional_feature_signs, compute_lead_time_hours


def package(plan, model_dir='b_model/model_regional_40'):
    evidence = PROJECT_ROOT / plan['evidence_dir']
    runs = PROJECT_ROOT / plan['output_dir']
    source = PROJECT_ROOT / plan['history']
    destination = (PROJECT_ROOT / model_dir).resolve()
    if not destination.is_relative_to((PROJECT_ROOT/'b_model').resolve()):
        raise ValueError('Regional model artifacts must stay in the Role B folder')
    if destination.exists():
        raise FileExistsError('Regional artifacts already packaged; use a new explicit version instead of overwriting')
    selection = json.loads((evidence/'selection.json').read_text())
    assert selection['frozen_before'] == 'final_2026'
    results = json.loads((evidence/'results.json').read_text())
    assert len(results) == len(plan['windows']) * 3 * len(HORIZONS)
    history, _ = load_history(source)
    indicators = add_leading_indicators(pd.read_parquet(source))[['cell_id','ts',*ENGINEERED_FEATURES]]
    history = history.merge(indicators,on=['cell_id','ts'],validate='one_to_one')
    parts = split_window(history, plan['windows'][-1])
    destination.mkdir()
    model_version = 'v1-regional40-20261017'
    metrics = {'model_version':model_version,'schema_version':'1.0','scope':'regional_40',
        'evaluation_note':'Retrospective final evaluation; per-horizon backend selected using earlier development folds only.',
        'horizons':{}}
    manifest = {'schema_version':'1.0','models':{}}
    final = { (r['backend'],r['horizon_h']):r for r in results if r['window']=='final_2026'}
    metadata = json.loads((evidence/'metadata.json').read_text())
    for h in HORIZONS:
        choice = selection['selected'][str(h)]
        backend = choice['spec']['backend']
        bag = joblib.load(runs/f'final_2026_{backend}_{h}h.joblib')
        columns = bag['feature_columns']
        Xtrain = bag['imputer'].transform(parts['train'][columns])
        Xcal = bag['imputer'].transform(parts['calibration'][columns])
        ytrain = parts['train'][f'target_{h}h'].to_numpy(dtype=int)
        ycal = parts['calibration'][f'target_{h}h'].to_numpy(dtype=int)
        calibrated = bag['model']
        base = calibrated.calibrated_classifiers_[0].estimator
        base = getattr(base,'estimator',base)
        signs = compute_directional_feature_signs(Xtrain,ytrain,columns)
        if backend=='xgboost':
            signs[-2:]=[1.,-1.]
        export_bundle(destination,h,choice['spec'],'sigmoid',base,calibrated,bag['imputer'],
            StandardScaler().fit(Xtrain),Xcal,ycal,{'seed':plan['seed'],'model_version':model_version,
                'feature_signs':signs.tolist(),'training_data':metadata},feature_columns=columns)
        manifest['models'][str(h)]={'filename':f'model_{h}h.joblib','format':'joblib',
            'model_version':model_version,'feature_order':columns,'positive_class':1,
            **({'feature_pipeline':PIPELINE_VERSION} if backend=='xgboost' else {})}
        selected = final[backend,h]
        m=selected['metrics'];baseline=final['dryness_baseline',h]['metrics']
        pred=pd.read_parquet(runs/f'final_2026_{backend}_{h}h_predictions.parquet')
        assert pred[['cell_id','ts']].reset_index(drop=True).equals(parts['validation'][['cell_id','ts']].reset_index(drop=True))
        lead=compute_lead_time_hours(parts['validation'],pred.label.to_numpy(),pred.score.to_numpy(),h)
        metrics['horizons'][str(h)]={'model_backend':backend,'pr_auc':m['pr_auc'],'roc_auc':m['roc_auc'],
            'baseline_pr_auc':baseline['pr_auc'],'baseline_roc_auc':baseline['roc_auc'],
            'precision':m['thresholds']['0.50']['precision'],'recall':m['thresholds']['0.50']['recall'],
            'classification_threshold':.5,'lead_time_hours':lead,'metrics':m,
            'quiet_metrics':selected['quiet_metrics'],'budgets':selected['budgets']}
    write_json(destination/'artifact_manifest.json',manifest)
    write_json(destination/'metrics.json',metrics)
    gate=assess_saved_metrics(metrics)
    write_json(destination/'quality_gate.json',gate)
    write_json(evidence/'selected_final_metrics.json',metrics)
    write_json(evidence/'quality_gate.json',gate)
    write_json(destination/'provenance.json',{'source_history':plan['history'],
        'source_history_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
        'cell_ids':sorted(history.cell_id.unique()),'cell_count':40,
        'split_audit':str((evidence/'split_final_2026.json').relative_to(PROJECT_ROOT)),
        'selection':str((evidence/'selection.json').relative_to(PROJECT_ROOT)),
        'quality_status':'provisional_retrospective_candidate' if gate['accepted'] else 'not_accepted_by_minimal_gate',
        'limitations':['Not an independent future or geographic test.','Calibrated probabilities require further reliability assessment.',
            'Regional predictions, not peat-only ignition or underground fire detection.'],
        'artifact_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in destination.glob('*.joblib')}})
    print(json.dumps(gate,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,default=PROJECT_ROOT/'b_model/conf/backtest_regional.yaml')
    parser.add_argument('--model-dir',default='b_model/model_regional_40')
    args=parser.parse_args()
    package(OmegaConf.to_container(OmegaConf.load(args.config),resolve=True),args.model_dir)
