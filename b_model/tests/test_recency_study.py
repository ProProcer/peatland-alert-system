"""Causal training weights, full policy purges, and development-only selection."""
import copy
import numpy as np
import pandas as pd
import pytest

from b_model.recency_study import recency_parts,select_strategies,training_weights


def test_decay_uses_training_time_and_balances_once_with_mean_one():
    ts=['2025-01-01T00:00:00Z','2025-01-02T00:00:00Z','2025-01-03T00:00:00Z','2025-01-04T00:00:00Z']
    y=np.array([0,1,0,1]);w,a=training_weights(ts,y,1)
    assert w[2]/w[0]==pytest.approx(4)
    assert w[3]/w[1]==pytest.approx(4)
    assert w.mean()==pytest.approx(1)
    assert w[y==0].sum()==pytest.approx(w[y==1].sum())
    full,_=training_weights(ts,y,None)
    np.testing.assert_array_equal(full,np.ones(4))
    with pytest.raises(ValueError):training_weights(ts,y,0)


def test_recent_window_and_probability_policy_validation_are_purged():
    t=pd.date_range('2025-01-01',periods=24*180,freq='h',tz='UTC')
    f=pd.DataFrame({'_time':t,'ts':t.strftime('%Y-%m-%dT%H:%M:%SZ'),'cell_id':'a'})
    for h in (24,48,72):f[f'target_{h}h']=np.arange(len(t))%2
    window={'name':'test','train_end':'2025-03-01T00:00:00Z','calibration_start':'2025-03-04T00:00:00Z',
        'calibration_end':'2025-04-01T00:00:00Z','validation_start':'2025-04-04T00:00:00Z','validation_end':'2025-05-01T00:00:00Z'}
    parts=recency_parts(f,window,{'recent_days':30})
    assert len(parts['train'])==30*24
    order=['train','probability_calibration','policy_calibration','validation']
    for a,b in zip(order,order[1:]):
        assert parts[a]._time.max()+pd.Timedelta(hours=72)<parts[b]._time.min()


def test_selection_rejects_final_rows_and_ap_regression_beyond_guard():
    rows=[{'window':fold,'strategy':name,'horizon_h':h,
        'quiet_metrics':{'pr_auc':quiet},'metrics':{'pr_auc':ap,'brier':.1}}
        for fold in ('a','b') for h in (24,48,72)
        for name,quiet,ap in (('full',.3,.5),('recent',.8,.4),('decay',.4,.49))]
    chosen,_=select_strategies(rows,['a','b'],.95)
    assert all(r['strategy']=='decay' for r in chosen.values())
    bad=copy.deepcopy(rows);bad[0]['window']='final'
    with pytest.raises(ValueError,match='development'):
        select_strategies(bad,['a','b'],.95)
