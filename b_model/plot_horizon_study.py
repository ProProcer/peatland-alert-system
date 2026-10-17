"""Standalone figures for the research-only horizon study (optional Matplotlib)."""
import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from b_model.config import PROJECT_ROOT


def plot(evidence):
    results=json.loads((evidence/'results.json').read_text())
    windows=list(dict.fromkeys(row['window'] for row in results))
    for figure_name, series, ylabel in (
        ('horizon_accuracy', [('accuracy','Model accuracy','#2563eb','o-'),
            ('always_hotspot_accuracy','Always hotspot','#ea580c','--'),
            ('always_no_hotspot_accuracy','Always no hotspot','#64748b',':'),
            ('balanced_accuracy','Balanced accuracy','#15803d','s-')], 'Percent'),
        ('horizon_ranking', [('pr_auc','Model Average Precision','#2563eb','o-'),
            ('positive_rate','Positive prevalence','#ea580c','--')], 'Score × 100')):
        fig,axes=plt.subplots(2,2,figsize=(11,7),sharex=True,sharey=True)
        for ax,window in zip(axes.flat,windows):
            rows=sorted([row for row in results if row['window']==window and row['status']=='evaluated'],key=lambda row:row['horizon_h'])
            days=[row['horizon_h']/24 for row in rows]
            for key,label,color,style in series:
                ax.plot(days,[100*row['metrics'][key] if row['metrics'][key] is not None else float('nan') for row in rows],style,label=label,color=color,linewidth=1.8,markersize=4)
            ax.set_title(window.replace('_',' '))
            ax.set_xticks([1,2,3,5,7,14]);ax.set_ylim(0,101)
            ax.set_xlabel('Forecast horizon (days)');ax.set_ylabel(ylabel)
            ax.grid(alpha=.2)
        fig.suptitle('Logistic Regression: forecast-horizon sensitivity',fontsize=15)
        handles,labels=axes.flat[0].get_legend_handles_labels()
        fig.legend(handles,labels,loc='lower center',ncol=len(series),frameon=False,bbox_to_anchor=(.5,.045))
        fig.text(.5,.015,'Retrospective • Same rows/settings per period • 14-day purges • Surface-hotspot occurrence',ha='center',fontsize=9)
        fig.tight_layout(rect=(0,.10,1,.94))
        for suffix in ('png','svg'):
            fig.savefig(evidence/f'{figure_name}.{suffix}',dpi=160)
        plt.close(fig)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence-dir',type=Path,default=PROJECT_ROOT/'b_model/experiment_results/20261017_horizons')
    plot(parser.parse_args().evidence_dir)
