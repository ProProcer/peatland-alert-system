"""Model rejection is a valid result, not a reason to falsify metrics."""
import copy
import pytest

from b_model.quality import assess_saved_metrics


def measurements():
    return {'horizons': {str(h): {'pr_auc': .3, 'baseline_pr_auc': .2,
        'roc_auc': .7, 'baseline_roc_auc': .6, 'recall': .4,
        'lead_time_hours': lead} for h,lead in ((24,10),(48,None),(72,2))}}


def test_nonmonotonic_or_unmeasured_lead_times_are_not_fabricated():
    assert assess_saved_metrics(measurements())['accepted']


def test_poor_average_precision_and_zero_recall_remain_acceptance_failures():
    data=measurements();data['horizons']['24'].update(pr_auc=.1,recall=0)
    report=assess_saved_metrics(data)
    assert not report['accepted']
    assert report['horizons']['24']['reasons']==[
        'average_precision_does_not_beat_recorded_baseline', 'no_positive_recall_at_recorded_cutoff']


@pytest.mark.parametrize('field,value',[('pr_auc',float('nan')),('recall',2),('lead_time_hours',25)])
def test_invalid_measurements_are_rejected(field,value):
    data=measurements();data['horizons']['24'][field]=value
    with pytest.raises(ValueError,match='Invalid'):
        assess_saved_metrics(data)
