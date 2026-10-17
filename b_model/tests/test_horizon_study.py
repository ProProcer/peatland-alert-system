"""Check raw-event label boundaries, horizon purges and accuracy baselines."""
import numpy as np
import pandas as pd
import pytest

from b_model.horizon_study import future_labels, metrics, study_parts


def test_future_window_excludes_now_includes_endpoint_and_filters_events():
    frame = pd.DataFrame({'cell_id':['a','b','c'],'ts':['2026-01-01T00:00:00Z']*3})
    events = pd.DataFrame({'cell_id':['a','a','b','c'],
        'ts':['2026-01-01T00:00:00Z','2026-01-02T00:00:00Z','2026-01-02T01:00:00Z','2026-01-01T02:00:00Z'],
        'alert_eligible':[True,True,True,False],'in_scope':[True]*4})
    coverage={'start':'2026-01-01T00:00:00Z','end_exclusive':'2026-02-01T00:00:00Z',
        'status':'human_declared_complete_local_J1V_J2V_exports'}
    result=future_labels(frame,events,[24,48],coverage)
    assert result.target_24h.tolist()==[1,0,0]
    assert result.target_48h.tolist()==[1,1,0]
    # Equality to the exclusive coverage endpoint is unknown, never negative.
    coverage['end_exclusive']='2026-01-02T00:00:00Z'
    assert future_labels(frame,events,[24],coverage).target_24h.isna().all()
    coverage['status']='unconfirmed'
    with pytest.raises(ValueError,match='coverage'):
        future_labels(frame,events,[24],coverage)


def test_purges_use_longest_horizon_and_common_validation_rows():
    t=pd.date_range('2025-01-01',periods=24*130,freq='h',tz='UTC')
    frame=pd.DataFrame({'_time':t})
    parts=study_parts(frame,'2025-04-01T00:00:00Z','2025-04-15T00:00:00Z',336,28)
    gap=pd.Timedelta(days=14)
    assert parts['train']._time.max()+gap<parts['calibration']._time.min()
    assert parts['calibration']._time.max()+gap<parts['validation']._time.min()
    assert len(parts['validation'])==14*24


def test_high_accuracy_from_majority_predictions_has_no_balanced_skill():
    y=np.array([1]*9+[0]);p=np.full(10,.9)
    result=metrics(y,p,.5)
    assert result['accuracy']==.9
    assert result['always_hotspot_accuracy']==.9
    assert result['balanced_accuracy']==.5
    assert result['accuracy_above_best_constant']==0
