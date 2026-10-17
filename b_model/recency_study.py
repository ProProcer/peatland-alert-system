"""Frozen recency strategies, separate probability/policy calibration, no promotion."""
import argparse
import hashlib
from pathlib import Path
import time
import warnings

import joblib
import numpy as np
from omegaconf import OmegaConf
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from b_model.alert_policy import policy_metrics,select_policy_threshold
from b_model.backtest import budget_metrics
from b_model.config import FEATURE_COLUMNS,HORIZONS,PROJECT_ROOT
from b_model.experiment import calibrate,load_history,probability_metrics,split_window,utc,write_json


def recency_parts(history,window,strategy):
    parts=split_window(history,window)
    if strategy['recent_days'] is not None:
        if strategy['recent_days']<=0:
            raise ValueError('Positive recent training duration required')
        parts['train']=parts['train'].loc[parts['train']._time>=utc(window['train_end'])-pd.Timedelta(days=strategy['recent_days'])]
    cs,ce=utc(window['calibration_start']),utc(window['calibration_end'])
    hours=(ce-cs)/pd.Timedelta(hours=1)
    width=int((hours-max(HORIZONS))//2)
    if width<1:
        raise ValueError('Calibration window too short for a full 72h internal purge')
    probability_end=cs+pd.Timedelta(hours=width)
    policy_start=probability_end+pd.Timedelta(hours=max(HORIZONS))
    calibration=parts.pop('calibration')
    parts['probability_calibration']=calibration.loc[calibration._time<probability_end]
    parts['policy_calibration']=calibration.loc[calibration._time>=policy_start]
    if any(p.empty for p in parts.values()):
        raise ValueError('Nonempty purged partitions required')
    for key in ('train','probability_calibration'):
        for h in HORIZONS:
            if parts[key][f'target_{h}h'].nunique()!=2:
                raise ValueError(f'{key} needs both classes for {h}h')
    return parts


def training_weights(timestamps,labels,half_life):
    y=np.asarray(labels)
    if not np.isin(y,[0,1]).all() or len(np.unique(y))!=2 or len(timestamps)!=len(y):
        raise ValueError('Aligned timestamps and both target classes required')
    y=y.astype(int)
    times=pd.DatetimeIndex(pd.to_datetime(timestamps,utc=True))
    age=np.asarray((times.max()-times)/pd.Timedelta(days=1),dtype=float)
    if half_life is not None and (not np.isfinite(half_life) or half_life<=0):
        raise ValueError('Positive finite decay half-life required')
    decay=np.ones(len(y)) if half_life is None else np.exp2(-age/half_life)
    if not np.isfinite(decay).all() or (decay<=0).any():
        raise ValueError('Decay weights must remain finite and positive')
    # Weighted class balancing, normalized to mean 1: no second class_weight.
    weights=decay.copy()
    for label in (0,1):
        mask=y==label;weights[mask]*=len(y)/(2*decay[mask].sum())
    return weights,{'half_life_days':half_life,'mean_weight':float(weights.mean()),
        'positive_weight_sum':float(weights[y==1].sum()),'negative_weight_sum':float(weights[y==0].sum()),
        'effective_sample_size':float(weights.sum()**2/(weights@weights)),
        'time_reference':'latest training timestamp only','class_weight':None}


def select_strategies(rows,folds,min_fraction):
    if any(r['window'] not in folds for r in rows):
        raise ValueError('Selection must contain development periods only')
    choices={};leaderboard=[]
    for h in HORIZONS:
        summaries=[]
        for name in sorted({r['strategy'] for r in rows}):
            group=[r for r in rows if r['strategy']==name and r['horizon_h']==h]
            if sorted(r['window'] for r in group)!=sorted(folds) or any(r['quiet_metrics']['pr_auc'] is None for r in group):
                raise ValueError('Every strategy requires all development folds with measurable quiet AP')
            summaries.append({'strategy':name,'horizon_h':h,
                'mean_quiet_ap':float(np.mean([r['quiet_metrics']['pr_auc'] for r in group])),
                'mean_overall_ap':float(np.mean([r['metrics']['pr_auc'] for r in group])),
                'mean_brier':float(np.mean([r['metrics']['brier'] for r in group]))})
        full=next(r for r in summaries if r['strategy']=='full')
        for r in summaries:
            r['eligible']=r['mean_overall_ap']>=min_fraction*full['mean_overall_ap']
        choices[str(h)]=sorted([r for r in summaries if r['eligible']],
            key=lambda r:(-r['mean_quiet_ap'],r['mean_brier'],r['strategy']))[0]
        leaderboard.extend(summaries)
    return choices,leaderboard


def run(plan):
    source=PROJECT_ROOT/plan['history'];output=PROJECT_ROOT/plan['output_dir'];evidence=PROJECT_ROOT/plan['evidence_dir']
    if any(not p.resolve().is_relative_to((PROJECT_ROOT/'b_model').resolve()) for p in (output,evidence)):
        raise ValueError('Study outputs must stay in Role B')
    if output.exists() or evidence.exists():
        raise FileExistsError('Use fresh run/evidence directories')
    sha=hashlib.sha256(source.read_bytes()).hexdigest()
    history,dropped=load_history(source)
    windows=OmegaConf.to_container(OmegaConf.load(PROJECT_ROOT/plan['reference_windows']))['windows']
    for p in (output,evidence):p.mkdir(parents=True);OmegaConf.save(OmegaConf.create(plan),p/'protocol.yaml')
    metadata={'source_sha256':sha,'complete_rows':len(history),'incomplete_labels_excluded':dropped,
        'evaluation_status':'Retrospective; dates and final results previously inspected. No fresh unseen test or automatic promotion.',
        'coverage_status':'Human confirms export query parameters/identical spatial coverage are unverified; no source overlap.',
        'weighting':'Decay and class balancing combined once in training loss; mean weight 1; no calibration reweighting.',
        'calibration':'First calibration slice fits sigmoid, then 72h purge, then separate policy calibration; final remains later.',
        'policy':'Daily 00Z, independently per horizon/pool; top-five cap then a calibration-only F1 threshold.',
        'risk_contract':'No changes to risk probabilities, fixed levels, horizons or C dispatch.'}
    write_json(evidence/'metadata.json',metadata)
    rows=[];daily=[];begin=time.perf_counter()
    for window in windows:
        if window['name']==windows[-1]['name']:
            chosen,board=select_strategies(rows,[w['name'] for w in windows[:-1]],
                plan['selection']['minimum_overall_ap_fraction_of_full'])
            write_json(evidence/'selection.json',{'selected':chosen,'leaderboard':board,
                'frozen_before':window['name'],'objective':plan['selection']})
        for strategy in plan['strategies']:
            parts=recency_parts(history,window,strategy)
            audit={k:{'rows':len(p),'start':p.ts.min(),'end':p.ts.max(),
                'positives':{str(h):int(p[f'target_{h}h'].sum()) for h in HORIZONS}} for k,p in parts.items()}
            write_json(evidence/f"split_{window['name']}_{strategy['name']}.json",audit)
            if parts['train'][FEATURE_COLUMNS].isna().all().any():raise ValueError('Entirely missing training predictor')
            imputer=SimpleImputer(strategy='median').fit(parts['train'][FEATURE_COLUMNS])
            X={k:imputer.transform(p[FEATURE_COLUMNS]) for k,p in parts.items()}
            for h in HORIZONS:
                y={k:p[f'target_{h}h'].to_numpy(dtype=int) for k,p in parts.items()}
                weights,weight_audit=training_weights(parts['train'].ts,y['train'],strategy['half_life_days'])
                base=make_pipeline(StandardScaler(),LogisticRegression(C=plan['logistic_c'][str(h)],
                    class_weight=None,max_iter=1000,random_state=plan['seed']))
                with warnings.catch_warnings():
                    warnings.filterwarnings('ignore',message='Unknown solver options: iprint')
                    base.fit(X['train'],y['train'],logisticregression__sample_weight=weights)
                fitted=calibrate(base,X['probability_calibration'],y['probability_calibration'],h,'sigmoid')
                policy_scores=fitted.predict_proba(X['policy_calibration'])[:,1]
                policies={}
                policy_frame=parts['policy_calibration']
                for pool in plan['policy']['pools']:
                    mask=policy_frame._time.dt.hour.eq(0).to_numpy()
                    if pool=='quiet':mask &= policy_frame.hotspots_in_cell_24h.eq(0).fillna(False).to_numpy(dtype=bool)
                    policies[pool]=select_policy_threshold(policy_frame.loc[mask],policy_scores[mask],
                        y['policy_calibration'][mask],plan['budget'])
                stem=f"{window['name']}_{strategy['name']}_{h}h"
                # Persist policies before evaluating this model's validation rows.
                write_json(output/f'{stem}_policy.json',policies)
                scores=fitted.predict_proba(X['validation'])[:,1];val=parts['validation']
                quiet=val.hotspots_in_cell_24h.eq(0).fillna(False).to_numpy(dtype=bool)
                result={'window':window['name'],'strategy':strategy['name'],'horizon_h':h,
                    'training_weights':weight_audit,'metrics':probability_metrics(y['validation'],scores),
                    'quiet_metrics':probability_metrics(y['validation'][quiet],scores[quiet]),'policies':policies,'budgets':{}}
                for cadence,cmask in (('daily_00z',val._time.dt.hour.eq(0).to_numpy()),('hourly',np.ones(len(val),dtype=bool))):
                    for pool,pmask in (('all',np.ones(len(val),dtype=bool)),('quiet',quiet)):
                        mask=cmask & pmask
                        metric,detail=budget_metrics(val.loc[mask],scores[mask],y['validation'][mask],plan['budget'])
                        result['budgets'][f'{cadence}_{pool}']=metric
                        if cadence=='daily_00z':
                            result['policies'][pool]['validation']=policy_metrics(val.loc[mask],scores[mask],
                                y['validation'][mask],plan['budget'],policies[pool]['threshold'])
                            daily.append(detail.assign(window=window['name'],strategy=strategy['name'],horizon_h=h,pool=pool))
                joblib.dump({'model':fitted,'imputer':imputer,'feature_columns':FEATURE_COLUMNS,'policies':policies},output/f'{stem}.joblib')
                pred=val[['cell_id','ts','hotspots_in_cell_24h']].copy();pred['label'],pred['score']=y['validation'],scores
                pred.to_parquet(output/f'{stem}_predictions.parquet',index=False)
                rows.append(result);write_json(evidence/'results.json',rows)
                print(stem,'AP',round(result['metrics']['pr_auc'],4),'quiet AP',round(result['quiet_metrics']['pr_auc'],4),
                    'quiet daily top5 hits',result['budgets']['daily_00z_quiet']['hits'],flush=True)
    pd.concat(daily,ignore_index=True).to_csv(evidence/'daily_budget.csv',index=False)
    pd.DataFrame([{'window':r['window'],'strategy':r['strategy'],'horizon_h':r['horizon_h'],
        'cadence_pool':k,**v} for r in rows for k,v in r['budgets'].items()]).to_csv(evidence/'budget_summary.csv',index=False)
    metadata.update(runtime_seconds=time.perf_counter()-begin,completed_models=len(rows))
    assert hashlib.sha256(source.read_bytes()).hexdigest()==sha
    write_json(evidence/'metadata.json',metadata)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,default=PROJECT_ROOT/'b_model/conf/recency_study.yaml')
    run(OmegaConf.to_container(OmegaConf.load(parser.parse_args().config),resolve=True))
