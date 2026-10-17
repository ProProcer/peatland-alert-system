"""Calibration-only thresholds, capped budgets and label-blind ranking."""
import numpy as np
import pandas as pd
import pytest

from b_model.alert_policy import policy_metrics,select_policy_threshold


def test_threshold_optimizes_whole_pool_f1_including_cap_misses():
    frame=pd.DataFrame({'ts':['2025-01-01T00:00:00Z']*3+['2025-01-02T00:00:00Z']*3,
        'cell_id':['a','b','c']*2})
    scores=np.array([.9,.8,.7,.6,.5,.4]);labels=np.array([0,0,1,1,0,1])
    result=select_policy_threshold(frame,scores,labels,1)
    assert result['threshold']==.6
    m=result['calibration_metrics']
    assert m['hits']==1 and m['false_alerts']==1 and m['positives']==3
    assert m['f1']==pytest.approx(2/5)  # Two positive windows remain outside cap.
    assert m['maximum_alerts_per_snapshot']==1


def test_threshold_is_frozen_when_applied_to_different_validation_labels():
    frame=pd.DataFrame({'ts':['2025-01-01T00:00:00Z']*2,'cell_id':['a','b']})
    scores=np.array([.7,.2]);policy=select_policy_threshold(frame,scores,[1,0],1)
    before=policy['threshold']
    result=policy_metrics(frame,scores,[0,1],1,before)
    assert result['hits']==0 and result['false_alerts']==1
    assert policy['threshold']==before==.7


def test_no_calibration_candidate_positive_disables_alerts_and_ties_are_stable():
    frame=pd.DataFrame({'ts':['2025-01-01T00:00:00Z']*2,'cell_id':['b','a']})
    policy=select_policy_threshold(frame,[.5,.5],[1,0],1)
    assert policy['threshold'] is None  # Label-blind tie selects a, whose label is zero.
    assert policy['calibration_metrics']['alerts']==0
    with pytest.raises(ValueError,match='binary'):
        select_policy_threshold(frame,[.5,.5],[.5,0],1)
