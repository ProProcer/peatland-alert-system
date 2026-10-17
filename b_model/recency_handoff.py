"""Export a reviewable recency candidate and frozen research policies, without promotion."""
import hashlib
import json
from pathlib import Path

import joblib
import numpy as np
from omegaconf import OmegaConf
from sklearn.preprocessing import StandardScaler

from b_model.config import FEATURE_COLUMNS,HORIZONS,PROJECT_ROOT
from b_model.experiment import export_bundle,load_history,write_json
from b_model.quality import assess_saved_metrics
from b_model.recency_study import recency_parts
from b_model.train import compute_directional_feature_signs


def package():
    plan=OmegaConf.to_container(OmegaConf.load(PROJECT_ROOT/'b_model/conf/recency_study.yaml'),resolve=True)
    evidence=PROJECT_ROOT/plan['evidence_dir'];runs=PROJECT_ROOT/plan['output_dir']
    output=PROJECT_ROOT/'b_model/model_recency_candidate'
    if output.exists():raise FileExistsError('Use a new explicit candidate version; existing artifacts are preserved')
    selection=json.loads((evidence/'selection.json').read_text());results=json.loads((evidence/'results.json').read_text())
    assert selection['frozen_before']=='final_2026' and len(results)==60
    source=PROJECT_ROOT/plan['history'];history,_=load_history(source)
    windows=OmegaConf.to_container(OmegaConf.load(PROJECT_ROOT/plan['reference_windows']))['windows']
    old=json.loads((PROJECT_ROOT/'b_model/model_regional_40/metrics.json').read_text())
    metadata=json.loads((evidence/'metadata.json').read_text())
    output.mkdir();manifest={'schema_version':'1.0','models':{}};operating={}
    metrics={'schema_version':'1.0','model_version':'v1-recency-review-20261017','horizons':{},
        'evaluation_status':'Retrospective review candidate; not promoted; matched controls and policy metrics are in recency results.'}
    for h in HORIZONS:
        name=selection['selected'][str(h)]['strategy']
        strategy=next(s for s in plan['strategies'] if s['name']==name)
        parts=recency_parts(history,windows[-1],strategy)
        result=next(r for r in results if r['window']=='final_2026' and r['strategy']==name and r['horizon_h']==h)
        bag=joblib.load(runs/f'final_2026_{name}_{h}h.joblib')
        Xtrain=bag['imputer'].transform(parts['train'][FEATURE_COLUMNS])
        Xcal=bag['imputer'].transform(parts['probability_calibration'][FEATURE_COLUMNS])
        ycal=parts['probability_calibration'][f'target_{h}h'].to_numpy(dtype=int)
        fitted=bag['model'];base=fitted.calibrated_classifiers_[0].estimator
        base=getattr(base,'estimator',base)
        signs=compute_directional_feature_signs(Xtrain,parts['train'][f'target_{h}h'].to_numpy(dtype=int))
        export_bundle(output,h,{'backend':'logistic_regression','strategy':strategy,
            'c':plan['logistic_c'][str(h)]},'sigmoid',base,fitted,bag['imputer'],StandardScaler().fit(Xtrain),
            Xcal,ycal,{'seed':plan['seed'],'model_version':metrics['model_version'],
                'feature_signs':signs.tolist(),'training_data':{**metadata,'strategy':strategy,
                    'training_weights':result['training_weights']} })
        exported=joblib.load(output/f'model_{h}h.joblib')
        np.testing.assert_array_equal(exported['primary_model'].predict_proba(Xcal),fitted.predict_proba(Xcal))
        manifest['models'][str(h)]={'filename':f'model_{h}h.joblib','format':'joblib',
            'model_version':metrics['model_version'],'feature_order':FEATURE_COLUMNS,'positive_class':1}
        m=result['metrics'];baseline=old['horizons'][str(h)]
        metrics['horizons'][str(h)]={'strategy':name,'pr_auc':m['pr_auc'],'roc_auc':m['roc_auc'],
            'baseline_pr_auc':baseline['baseline_pr_auc'],'baseline_roc_auc':baseline['baseline_roc_auc'],
            'baseline_note':'Previously calibrated dryness model on identical final dates/labels; calibration slice differs.',
            'recall':m['thresholds']['0.50']['recall'],'precision':m['thresholds']['0.50']['precision'],
            'classification_threshold':.50,'lead_time_hours':None,'metrics':m,'quiet_metrics':result['quiet_metrics']}
        operating[str(h)]={'strategy':name,'policies':{
            pool:{k:v for k,v in p.items() if k!='validation'} for pool,p in result['policies'].items()},
            'probability_calibration_end':parts['probability_calibration'].ts.max(),
            'policy_calibration_start':parts['policy_calibration'].ts.min(),
            'policy_calibration_end':parts['policy_calibration'].ts.max()}
    write_json(output/'artifact_manifest.json',manifest);write_json(output/'metrics.json',metrics)
    write_json(output/'quality_gate.json',assess_saved_metrics(metrics))
    write_json(output/'operating_points.json',{'status':'Research review only; no change to fixed risk levels or C policy.',
        'cadence':'daily_00z','budget':5,'scope':'regional_40','horizons':operating})
    write_json(output/'provenance.json',{'source_history':plan['history'],
        'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
        'selection':str((evidence/'selection.json').relative_to(PROJECT_ROOT)),
        'status':'experimental_review_candidate_not_promoted',
        'scope_cell_ids':sorted(history.cell_id.unique()),'source_coverage':'Declared, original export settings unverified.',
        'artifact_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in output.glob('*.joblib')}})
    print('Exported isolated recency candidate and calibration-only policy settings; current handoff unchanged.')


if __name__=='__main__':package()
