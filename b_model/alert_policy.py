"""Research alert operating points; frozen risk levels and C dispatch stay intact."""
import numpy as np
import pandas as pd


def capped_indices(frame, scores, budget):
    if isinstance(budget, bool) or not isinstance(budget, int) or budget < 1:
        raise ValueError('Positive integer alert budget required')
    p = np.asarray(scores, dtype=float)
    if p.shape != (len(frame),) or not np.isfinite(p).all() or ((p<0)|(p>1)).any():
        raise ValueError('Aligned finite probabilities required')
    if frame.duplicated(['ts','cell_id']).any() or frame[['ts','cell_id']].isna().any().any():
        raise ValueError('Unique nonmissing timestamp/cell keys required')
    rows = frame[['ts','cell_id']].reset_index(drop=True).assign(score=p,position=np.arange(len(frame)))
    rows = rows.sort_values(['ts','score','cell_id'],ascending=[True,False,True])
    return rows.loc[rows.groupby('ts').cumcount()<budget,'position'].to_numpy(dtype=int)


def policy_metrics(frame, scores, labels, budget, threshold):
    y = np.asarray(labels)
    p = np.asarray(scores, dtype=float)
    if y.shape != p.shape or not np.isin(y,[0,1]).all():
        raise ValueError('Aligned binary policy labels required')
    selected = np.zeros(len(frame),dtype=bool)
    indices = capped_indices(frame,p,budget)
    if threshold is not None:
        if isinstance(threshold,bool) or not np.isfinite(threshold) or not 0<=threshold<=1:
            raise ValueError('Threshold must be null (disabled) or a probability')
        selected[indices] = p[indices]>=threshold
    tp=int(np.sum(selected & (y==1)));fp=int(np.sum(selected & (y==0)))
    positives=int(np.sum(y));alerts=tp+fp
    per=pd.DataFrame({'ts':frame.ts.to_numpy(),'selected':selected}).groupby('ts').selected.sum()
    return {'rows':len(frame),'snapshots':frame.ts.nunique(),'positives':positives,
        'threshold':threshold,'budget':budget,'alerts':alerts,'hits':tp,'false_alerts':fp,
        'missed_positive_windows':positives-tp,'precision':tp/alerts if alerts else None,
        'recall':tp/positives if positives else None,
        'f1':2*tp/(alerts+positives) if alerts+positives else 0.,
        'maximum_alerts_per_snapshot':int(per.max()) if len(per) else 0,
        'mean_alerts_per_snapshot':alerts/len(per) if len(per) else 0.}


def select_policy_threshold(frame, scores, labels, budget):
    """Choose from policy-calibration rows only; denominator includes cap misses.

    F1 is computed on the whole eligible pool, including positives outside top-k.
    The cap is applied before thresholding. Equal F1 chooses the higher threshold.
    No candidate positive means an explicitly disabled policy rather than FP alerts.
    """
    y = np.asarray(labels);p=np.asarray(scores,dtype=float)
    if y.shape != p.shape or not np.isin(y,[0,1]).all():
        raise ValueError('Aligned binary policy labels required')
    y=y.astype(int)
    idx=capped_indices(frame,p,budget)
    order=idx[np.argsort(-p[idx],kind='stable')]
    if not len(order) or not y[order].sum():
        threshold=None
    else:
        cumulative=np.cumsum(y[order]);ends=np.r_[p[order][1:]!=p[order][:-1],True]
        positions=np.flatnonzero(ends)
        f1=2*cumulative[positions]/(positions+1+y.sum())
        # Descending scores: first maximum gives the highest threshold.
        threshold=float(p[order[positions[np.flatnonzero(f1==f1.max())[0]]]])
    return {'threshold':threshold,'selection_split':'policy_calibration_only',
        'objective':'maximum F1 after daily top-k cap; highest threshold breaks ties',
        'calibration_metrics':policy_metrics(frame,p,y,budget,threshold)}
