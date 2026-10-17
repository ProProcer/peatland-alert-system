"""Export daily historical measurements for the read-only analytics page.

No risk files, target labels, model artifacts or inference are read.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIELDS = [
 ('temp_c','Air temperature','°C','mean'),('precip_mm','Daily rainfall','mm','sum_complete'),
 ('wind_kmh','Wind speed','km/h','mean'),('wind_dir_deg','Wind direction','?','circular_mean'),('sm_0_1','Soil moisture · 0–1 cm','m³/m³','mean'),
 ('sm_1_3','Soil moisture · 1–3 cm','m³/m³','mean'),('sm_3_9','Soil moisture · 3–9 cm','m³/m³','mean'),
 ('sm_9_27','Soil moisture · 9–27 cm','m³/m³','mean'),('sm_27_81','Deep soil moisture · 27–81 cm','m³/m³','mean'),
 ('vpd_kpa','Vapour pressure deficit','kPa','mean'),('soil_temp_0_c','Surface soil temperature','°C','mean'),
 ('soil_temp_18_c','Soil temperature · 18 cm','°C','mean'),('et_mm','Daily evapotranspiration','mm','sum_complete'),
 ('et0_mm','Daily reference evapotranspiration','mm','sum_complete'),
 ('rain_24h_mm','Rolling rainfall · 24 hours','mm','last'),('rain_7d_mm','Rolling rainfall · 7 days','mm','last'),
 ('rain_30d_mm','Rolling rainfall · 30 days','mm','last'),('days_since_rain','Days since rain','days','last'),
 ('sm_27_81_delta_7d','Deep moisture change · 7 days','m³/m³','last'),
 ('vpd_mean_24h','Rolling mean VPD · 24 hours','kPa','last'),('soil_air_temp_gap_c','Soil–air temperature gap','°C','mean'),
 ('hotspots_in_cell_24h','Rolling hotspots in cell · 24 hours','count','max'),
 ('hotspots_10km_7d','Rolling nearby hotspots · 7 days','count','max'),
 ('frp_sum_10km_7d','Rolling nearby fire radiative power · 7 days','MW','max'),
 ('nearest_hotspot_km','Nearest hotspot distance','km','min')]


def atomic_json(path, data):
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(data,ensure_ascii=False,allow_nan=False,separators=(',',':')),encoding='utf-8')
    temporary.replace(path)


def aggregate(frame):
    import pandas as pd
    frame=frame.sort_values('ts').copy()
    times=pd.to_datetime(frame['ts'],utc=True)
    if times.duplicated().any():
        raise ValueError('Duplicate historical timestamps within a cell')
    frame['date']=times.dt.strftime('%Y-%m-%d')
    result=[]
    for date,group in frame.groupby('date',sort=True):
        values=[]; valid=[]
        for name,_,_,method in FIELDS:
            series=group[name]; count=int(series.count());valid.append(count)
            if count==0:value=None
            elif method=='sum_complete':value=float(series.sum()) if count==24 and len(group)==24 else None
            elif method=='circular_mean':
                import math
                angles=[math.radians(float(v)) for v in series.dropna()]
                sine=sum(math.sin(v) for v in angles)/count
                cosine=sum(math.cos(v) for v in angles)/count
                value=math.degrees(math.atan2(sine,cosine))%360 if math.hypot(sine,cosine)>1e-10 else None
            elif method=='last':value=float(series.iloc[-1]) if pd.notna(series.iloc[-1]) else None
            else:value=float(getattr(series,method)())
            values.append(round(value,6) if value is not None else None)
        result.append({'date':date,'hours':len(group),'values':values,'valid':valid})
    return result


def main():
    import pandas as pd
    source=ROOT/'data/demo/role_a_real/regional_40'
    destination=ROOT/'d_frontend/assets/historical'
    selection=json.loads((source/'selection.json').read_text(encoding='utf-8'))
    points=selection['cells']
    ids={p['cell_id'] for p in points}
    frame=pd.read_parquet(source/'history.parquet',columns=['cell_id','ts',*[row[0] for row in FIELDS]])
    if set(frame.cell_id)!=ids or len(ids)!=40:
        raise ValueError('Expected historical measurements for exactly the 40 selected points')
    manifest={'version':1,'source':'data/demo/role_a_real/regional_40/history.parquet','fields':[{'key':key,'label':label,'unit':unit,'aggregation':method} for key,label,unit,method in FIELDS], 'points':[],
              'note':'Historical measurements only. Weather and soil data are modeled; hotspots are satellite detections. Rolling hotspot counts are not unique daily fire totals. Daily totals require 24 non-null hourly values.'}
    for point in points:
        subset=frame[frame.cell_id==point['cell_id']]
        rows=aggregate(subset)
        filename=point['cell_id']+'.json'
        atomic_json(destination/filename,{'cell_id':point['cell_id'],'rows':rows})
        manifest['points'].append({'cell_id':point['cell_id'],'province':point['province'],'lat':point['lat'],'lon':point['lon'],
            'peat_fraction':point['peat_fraction'],'peat_area_km2':point['peat_area_km2'],'file':filename,'start':rows[0]['date'],'end':rows[-1]['date'],'days':len(rows),'hours':len(subset),
            'mean_temp_c':float(subset.temp_c.mean()) if subset.temp_c.count() else None,
            'mean_sm_27_81':float(subset.sm_27_81.mean()) if subset.sm_27_81.count() else None,
            'complete_days':sum(r['hours']==24 for r in rows)})
    atomic_json(destination/'manifest.json',manifest)
    print(f'Exported historical measurements: {len(points)} points, {len(frame):,} hourly records, {sum(p["days"] for p in manifest["points"]):,} cell-days')


if __name__=='__main__':main()
