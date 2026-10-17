"""Read-only audit of the actual FIRMS exports; no relabeling or source writes."""
from collections import Counter
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from b_model.config import PROJECT_ROOT
from b_model.experiment import write_json


def audit(output):
    if output.exists():raise FileExistsError('Use a fresh source audit directory')
    manifest=json.loads((PROJECT_ROOT/'data/demo/role_a_real/source_manifest.json').read_text())
    records=[]
    for entry in manifest['sources']:
        path=PROJECT_ROOT/entry['path']
        if path.suffix!='.csv':continue
        sha=hashlib.sha256(path.read_bytes()).hexdigest()
        if sha!=entry['sha256']:raise ValueError('Raw source hash changed; producer review required')
        counters={k:Counter() for k in ('confidence','satellite','instrument','version','type')}
        date_min=None;date_max=None;dates=set();count=0
        bounds=[np.inf,np.inf,-np.inf,-np.inf]
        for chunk in pd.read_csv(path,dtype=str,chunksize=200000,usecols=lambda c:c in {
            'latitude','longitude','acq_date','confidence','satellite','instrument','version','type'}):
            count+=len(chunk)
            for key,counter in counters.items():
                counter.update(chunk[key].fillna('unavailable').str.strip() if key in chunk else ['unavailable']*len(chunk))
            days=chunk.acq_date.dropna();dates.update(days.unique())
            if len(days):
                lo,hi=days.min(),days.max()
                date_min=lo if date_min is None else min(date_min,lo)
                date_max=hi if date_max is None else max(date_max,hi)
            lat=pd.to_numeric(chunk.latitude,errors='coerce');lon=pd.to_numeric(chunk.longitude,errors='coerce')
            bounds=[min(bounds[0],lon.min()),min(bounds[1],lat.min()),max(bounds[2],lon.max()),max(bounds[3],lat.max())]
        records.append({'path':entry['path'],'sha256':sha,'hash_matches_manifest':True,'rows':count,
            'product':'archive' if 'archive' in path.name else 'nrt',
            'observed_date_min':date_min,'observed_date_max':date_max,'distinct_detection_dates':len(dates),
            'observed_detection_bounds_west_south_east_north':bounds,
            'bounds_note':'Envelope of observed detections only, not proof of original query box or completeness.',
            **{key:dict(value) for key,value in counters.items()}})
    history=pd.read_parquet(PROJECT_ROOT/'data/demo/role_a_real/regional_40/history.parquet')
    events=pd.read_parquet(PROJECT_ROOT/'data/demo/role_a_real/firms_normalized.parquet')
    selected=events.loc[events.cell_id.isin(set(history.cell_id)) & events.in_scope].copy()
    selected['product']=selected.source_file.str.extract('(archive|nrt)',expand=False)
    selected['month']=selected.ts.str[:7]
    monthly=selected.groupby(['month','product','satellite']).agg(detections=('ts','size'),eligible=('alert_eligible','sum')).reset_index()
    kinds=selected.assign(type=selected.type.fillna('unavailable')).groupby(['product','type']).size().reset_index(name='detections')
    rates=history.assign(month=history.ts.str[:7]).groupby('month').agg(rows=('cell_id','size'),
        observed_24h=('target_24h','count'),positive_24h=('target_24h','sum')).reset_index()
    rates['positive_rate_24h']=rates.positive_24h/rates.observed_24h
    overlap={}
    for sat in ('N20','N21'):
        archive=[r for r in records if r['product']=='archive' and sat in r['satellite']]
        nrt=[r for r in records if r['product']=='nrt' and sat in r['satellite']]
        overlap[sat]={'archive_end':max(r['observed_date_max'] for r in archive),
            'nrt_start':min(r['observed_date_min'] for r in nrt)}
        overlap[sat]['date_ranges_overlap']=overlap[sat]['archive_end']>=overlap[sat]['nrt_start']
    result={'status':'UNRESOLVED_EXPORT_COVERAGE_AND_SOURCE_ATTRIBUTION','files':records,
        'product_date_overlap':overlap,'regional_40_monthly_detections':monthly.to_dict('records'),
        'regional_40_type_availability':kinds.to_dict('records'),'regional_40_label_rates':rates.to_dict('records'),
        'duplicate_normalized_acquisition_keys':int(events.duplicated(['satellite','ts','latitude','longitude']).sum()),
        'producer_confirmation':{'overlapping_exports':False,'original_query_parameters_saved':False,
            'identical_spatial_export_filters_verified':False,
            'statement':'Human relayed Role A confirmation: files switch on July 1; no saved bbox/filter/download parameters prove equal export coverage.'},
        'established':['Both products contain VIIRS N20/N21 observations; no satellite switch explains the boundary.',
            'Existing A normalization applies the same confidence n/h test and geometric scope to both products.',
            'A common downstream region filter cannot recover detections omitted by an upstream export.',
            'Observed bounds, detections on a date and zero rows cannot establish observation/export completeness.',
            'The July product switch alone cannot distinguish seasonality from source/export effects.'],
        'not_established':['How much of the increase is actual fire activity.','Whether upstream spatial/type filters were identical.',
            'Continuous observation availability or false-negative label validity independent of the human declaration.'],
        'label_action':'No labels, class definitions, producer files or missing values changed.',
        'official_sources':[{'url':'https://firms.modaps.eosdis.nasa.gov/content/academy/data_api/firms_api_use.html',
            'supports':'NRT/SP distinction, multi-month SP availability lag, MAP_KEY requirement and data-availability endpoint.'},
            {'url':'https://firms.modaps.eosdis.nasa.gov/api/data_availability/',
             'supports':'Check actual product date availability before requesting a controlled comparison.'}]}
    output.mkdir(parents=True)
    write_json(output/'audit.json',result)
    monthly.to_csv(output/'monthly_detections.csv',index=False);rates.to_csv(output/'monthly_label_rates.csv',index=False)
    request={'recipient':'Role A / data owner','delivery':'Prepared only; no external message sent.',
        'required_to_resolve':'Original export receipts/settings or same-date re-exports using explicit identical filters.',
        'proposed_new_controlled_bbox_west_south_east_north':[108,-5,120,5],
        'bbox_note':'Proposed control box, not claimed original coverage; apply the same existing Kalimantan boundary and frozen 40-cell IDs afterward.',
        'satellites':['N20','N21'],'processing_products':['archive/standard','NRT'],
        'dates':'A common seven-day period available in both products, determined from official availability or retained NRT archives; do not assume overlap exists.',
        'filters':'Same collection, confidence n/h, day/night selection, spatial scope; retain type and versions without silently changing eligibility.',
        'save':['query URL with credentials removed','product ID and collection','explicit query bbox/region','start/end UTC and inclusivity',
                'confidence/type/day-night filters','download timestamp','file SHA-256','coverage/availability declaration'],
        'compare':['Counts by day/satellite/cell','Acquisition-time/location matches with documented coordinate tolerance',
                   'Confidence/type differences','Remaining unmatched detections and reasons'],
        'if_no_overlap_available':'Record source attribution as unresolved; retain a consistent-product evaluation and acquire prospective paired observations when available.'}
    write_json(output/'role_a_request.json',request)
    print('Audited four original source files. Attribution remains unresolved; exact Role A evidence request saved.')


if __name__=='__main__':
    audit(PROJECT_ROOT/'b_model/experiment_results/20261017_source_consistency')
