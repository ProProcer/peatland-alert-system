"""Separate model acceptance from software correctness. Never alter scores."""
import argparse
import json
import math
from pathlib import Path

from b_model.config import HORIZONS


def assess_saved_metrics(metrics):
    """Gate a candidate against its own recorded baseline and nonzero recall.

    This minimal ranking gate is not operational approval, nor evidence of
    calibrated probabilities. Missing measurements cannot satisfy acceptance.
    """
    results = {}
    for h in HORIZONS:
        row = metrics['horizons'][str(h)]
        for key in ('pr_auc', 'baseline_pr_auc', 'roc_auc', 'baseline_roc_auc', 'recall'):
            value = row.get(key)
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))
                                      or not math.isfinite(value) or not 0 <= value <= 1):
                raise ValueError(f'Invalid {key} for {h}h')
        lead = row.get('lead_time_hours')
        if lead is not None and (isinstance(lead, bool) or not isinstance(lead, (int, float))
                                 or not math.isfinite(lead) or not 0 <= lead <= h):
            raise ValueError(f'Invalid measured lead time for {h}h')
        ap, baseline, recall = [row.get(k) for k in ('pr_auc', 'baseline_pr_auc', 'recall')]
        reasons = []
        if ap is None or baseline is None:
            reasons.append('average_precision_or_baseline_unmeasured')
        elif ap <= baseline:
            reasons.append('average_precision_does_not_beat_recorded_baseline')
        if recall is None or recall <= 0:
            reasons.append('no_positive_recall_at_recorded_cutoff')
        results[str(h)] = {'accepted': not reasons, 'reasons': reasons,
            'pr_auc': ap, 'baseline_pr_auc': baseline, 'recall': recall,
            'lead_time_hours': lead}
    return {'accepted': all(r['accepted'] for r in results.values()),
        'scope': 'Minimal candidate gate on its own recorded evaluation; not operational approval.',
        'horizons': results}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('metrics', type=Path)
    result = assess_saved_metrics(json.loads(parser.parse_args().metrics.read_text()))
    print(json.dumps(result, indent=2, allow_nan=False))
    raise SystemExit(0 if result['accepted'] else 1)
