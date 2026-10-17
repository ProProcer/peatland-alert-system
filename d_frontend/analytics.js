(() => {
  'use strict';
  const format = value => value == null || !Number.isFinite(value) ? 'Unavailable' : Number(value).toLocaleString('en-US',{maximumFractionDigits:3});
  function filterDays(rows,from,to){return rows.filter(row=>(!from||row.date>=from)&&(!to||row.date<=to));}
  function statistics(rows,index){const values=rows.map(row=>row.values[index]).filter(Number.isFinite);return {count:values.length,mean:values.length?values.reduce((a,b)=>a+b,0)/values.length:null,min:values.length?Math.min(...values):null,max:values.length?Math.max(...values):null};}
  function selectPointRisks(rows,ids){
    const selected=new Map();
    for(const row of rows){
      if(!ids.has(row.cell_id))continue;
      const score=row.risk_score;
      const expected=score<.35?'LOW':score<.6?'MODERATE':score<.8?'HIGH':'CRITICAL';
      if(!Number.isFinite(score)||score<0||score>1||row.risk_level!==expected||![24,48,72].includes(row.horizon_h)||!Number.isFinite(Date.parse(row.ts)))throw new Error('Invalid risk record');
      const previous=selected.get(row.cell_id);
      if(!previous||Date.parse(row.ts)>Date.parse(previous.ts)||(row.ts===previous.ts&&(score>previous.risk_score||(score===previous.risk_score&&row.horizon_h<previous.horizon_h))))selected.set(row.cell_id,row);
    }
    return selected;
  }
  if(typeof module!=='undefined'&&module.exports){module.exports={filterDays,statistics,format,selectPointRisks};return;}
  const $=id=>document.getElementById(id);
  const node=(tag,text,cls)=>{const item=document.createElement(tag);if(text!=null)item.textContent=text;if(cls)item.className=cls;return item;};
  const svg=(tag,attrs,text)=>{const item=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const [key,value] of Object.entries(attrs))item.setAttribute(key,value);if(text!=null)item.textContent=text;return item;};
  let manifest=null,selected=null,allRows=[],filtered=[],page=0,loadVersion=0,inspection=0,plot=null;
  let dayPinned=false;
  const cache=new Map();
  let latestRisks=new Map();
  const metricIndex=()=>Number($('measurement').value||0);
  function visiblePoints(){const query=$('point-search').value.toLowerCase(),province=$('province-filter').value,sort=$('point-sort').value;return manifest.points.filter(point=>(!province||point.province===province)&&`${point.cell_id} ${point.province}`.toLowerCase().includes(query)).sort((a,b)=>{if(sort==='risk')return (latestRisks.get(b.cell_id)?.risk_score??-1)-(latestRisks.get(a.cell_id)?.risk_score??-1);if(sort==='temperature')return (b.mean_temp_c??-Infinity)-(a.mean_temp_c??-Infinity);if(sort==='moisture')return (a.mean_sm_27_81??Infinity)-(b.mean_sm_27_81??Infinity);return sort==='id'?a.cell_id.localeCompare(b.cell_id):a.province.localeCompare(b.province)||a.cell_id.localeCompare(b.cell_id);});}
  function renderPoints(){const target=$('points-list');target.replaceChildren();const points=visiblePoints();$('point-count').textContent=`${points.length} / ${manifest.points.length} points`;for(const point of points){const row=node('tr');row.classList.toggle('selected',point.cell_id===selected?.cell_id);const label=node('td'),button=node('button',point.cell_id);button.type='button';button.setAttribute('aria-pressed',String(point.cell_id===selected?.cell_id));button.onclick=()=>choose(point);label.append(button,node('small',point.province));const risk=latestRisks.get(point.cell_id),riskCell=node('td');riskCell.append(riskBadge(risk));row.append(label,riskCell,node('td',format(point.mean_temp_c)),node('td',format(point.mean_sm_27_81)));row.onclick=event=>{if(!event.target.closest('button'))choose(point);};target.append(row);}if(!points.length){const row=node('tr'),cell=node('td','No points match your filters.');cell.colSpan=4;row.append(cell);target.append(row);}}
  function riskBadge(risk){
    const badge=node('span',risk?risk.risk_level:'Unavailable',risk?`badge analytics-risk-badge ${risk.risk_level}`:'analytics-risk-unavailable');
    if(risk)badge.title=`${(risk.risk_score*100).toFixed(1)}% / ${risk.horizon_h}h / ${risk.ts}`;
    return badge;
  }
  async function loadLatestRisks(){
    latestRisks=new Map();
    try{
      let rows;
      let response;
      try{response=await fetch('/demo/coverage/risk.json',{cache:'no-store'});}catch(error){response=null;}
      if(response?.ok)rows=await response.json();
      else if(!response||response.status===404){
        const bundled=await fetch('assets/coverage-snapshot.json',{cache:'no-store'});
        if(!bundled.ok)throw new Error('Risk snapshot unavailable');
        rows=(await bundled.json()).feeds?.['risk.json'];
      }else throw new Error('Risk feed unavailable');
      if(!Array.isArray(rows))throw new Error('Risk feed invalid');
      latestRisks=selectPointRisks(rows,new Set(manifest.points.map(point=>point.cell_id)));
      const times=[...latestRisks.values()].map(row=>row.ts).sort();
      $('analytics-risk-note').textContent=latestRisks.size?`Latest forecast risk: highest level across 24/48/72 hours at each point's latest snapshot.`:'No risk predictions supplied. Historical measurements remain available.';
    }catch(error){$('analytics-risk-note').textContent='Latest forecast risk is unavailable. Historical measurements remain available.';}
  }
  async function choose(point){setDayPinned(false);selected=point;$('selected-risk').replaceChildren(riskBadge(latestRisks.get(point.cell_id)));const url=new URL(window.location.href);url.searchParams.set('cell',point.cell_id);window.history.replaceState(null,'',url);document.querySelector('.points-panel').hidden=true;$('point-explorer').hidden=false;$('analytics-main').classList.add('showing-point');allRows=[];filtered=[];plot=null;page=0;renderPoints();$('selected-title').textContent=point.cell_id;$('selected-location').textContent=`${point.province} · ${point.lat}°, ${point.lon}° · ${point.start} to ${point.end}`;$('history-status').textContent='Loading daily records…';$('history-chart').replaceChildren();$('history-records').replaceChildren();$('daily-measurements').replaceChildren();$('point-statistics').replaceChildren();$('day-reading').textContent='Loading…';$('chart-tooltip').hidden=true;const ticket=++loadVersion;$('export-history').disabled=true;try{let data=cache.get(point.cell_id);if(!data){const response=await fetch(`assets/historical/${encodeURIComponent(point.file)}`,{cache:'no-store'});if(!response.ok)throw new Error(`History request failed (${response.status})`);data=await response.json();if(data.cell_id!==point.cell_id||!Array.isArray(data.rows))throw new Error('Historical point identity mismatch');cache.set(point.cell_id,data);}if(ticket!==loadVersion)return;allRows=data.rows;$('history-from').min=point.start;$('history-from').max=point.end;$('history-to').min=point.start;$('history-to').max=point.end;$('history-from').value=point.start;$('history-to').value=point.end;renderHistory();$('selected-title').focus({preventScroll:true});$('point-explorer').scrollIntoView({block:'start',behavior:'instant'});}catch(error){if(ticket!==loadVersion)return;$('history-status').textContent=`Could not load this point: ${error.message}`;$('day-reading').textContent='Historical measurements unavailable.';}}
  function renderHistory(){const pinnedDate=dayPinned?filtered[inspection]?.date:null;const from=$('history-from').value,to=$('history-to').value;filtered=filterDays(allRows,from,to);page=0;const pinnedIndex=pinnedDate?filtered.findIndex(row=>row.date===pinnedDate):-1;inspection=pinnedIndex>=0?pinnedIndex:Math.max(0,filtered.length-1);if(pinnedIndex<0)setDayPinned(false);const field=manifest.fields[metricIndex()],stats=statistics(filtered,metricIndex());$('history-status').textContent=from&&to&&from>to?'The start date must be on or before the end date.':`${filtered.length.toLocaleString()} daily records · ${stats.count.toLocaleString()} days with this measurement`;const target=$('point-statistics');target.replaceChildren();for(const [label,value] of [['Average',stats.mean],['Minimum',stats.min],['Maximum',stats.max]]){const card=node('div');card.append(node('strong',format(value)),node('span',`${label} · ${field.unit}`));target.append(card);}$('aggregation-note').textContent=({circular_mean:'Circular mean of available hourly wind directions (0? = north). Opposing directions can have no defined mean; wraparound at 360? is not a large direction change.',mean:'',sum_complete:'Daily totals are shown only when all 24 hourly measurements are present. Incomplete days remain unavailable.',last:'Each daily value is the final hourly record of that UTC day. A missing final record value remains unavailable.',max:'Daily maximum of an existing rolling measure. Counts and rolling totals overlap between days and must not be added together.',min:'Daily minimum of the available hourly distances.'})[field.aggregation];$('chart-tooltip').hidden=true;$('export-history').disabled=!filtered.length;drawChart();renderTable();inspect(inspection,dayPinned);}
  function drawChart(){const chart=$('history-chart');chart.replaceChildren();const title=svg('title',{id:'chart-title'},`${manifest.fields[metricIndex()].label} · ${selected.cell_id}`),desc=svg('desc',{id:'chart-description'},'Daily historical input measurements. Hover to preview a day, click to pin it, or select a date in the records table. Use Escape to release a pinned day. Gaps indicate missing days or values.');chart.append(title,desc);const index=metricIndex(),valid=filtered.filter(row=>Number.isFinite(row.values[index]));plot=null;if(!valid.length){chart.append(svg('text',{x:380,y:135,'text-anchor':'middle'},'No measurements available in this date range'));return;}const dates=filtered.map(row=>Date.parse(row.date+'T00:00:00Z'));const first=dates[0],last=dates.at(-1),min=Math.min(...valid.map(row=>row.values[index])),max=Math.max(...valid.map(row=>row.values[index]));const pad=Math.max((max-min)*.12,Math.abs(max)*.03,.001),lo=min-pad,hi=max+pad;const x=ts=>56+(last===first?320:(ts-first)/(last-first)*676),y=value=>224-(value-lo)/(hi-lo)*196;plot={x,y,dates,first,last};for(let i=0;i<=4;i++){const yy=28+i*49;chart.append(svg('line',{x1:56,x2:732,y1:yy,y2:yy,class:'chart-grid'}),svg('text',{x:48,y:yy+4,'text-anchor':'end'},format(hi-(hi-lo)*i/4)));}chart.append(svg('text',{x:56,y:251},filtered[0].date),svg('text',{x:732,y:251,'text-anchor':'end'},filtered.at(-1).date));let path='',previous=null;for(let i=0;i<filtered.length;i++){const row=filtered[i],value=row.values[index],ts=dates[i];if(!Number.isFinite(value)){previous=null;continue;}const connected=previous!=null&&ts-previous===86400000;path+=`${connected?'L':'M'}${x(ts).toFixed(2)},${y(value).toFixed(2)} `;previous=ts;}chart.append(svg('path',{d:path,class:'chart-line'}));if(valid.length===1)chart.append(svg('circle',{cx:x(Date.parse(valid[0].date+'T00:00:00Z')),cy:y(valid[0].values[index]),r:4,class:'chart-point'}));chart.append(svg('circle',{id:'inspected-chart-point',r:5,class:'chart-point',visibility:'hidden'}));}
  function inspect(index,reveal=false){inspection=Number(index);if(dayPinned)updatePinStatus();const row=filtered[inspection],field=manifest.fields[metricIndex()];$('day-reading').textContent=row?`${row.date} UTC · ${field.label}: ${format(row.values[metricIndex()])} ${row.values[metricIndex()]!=null?field.unit:''} · ${row.valid[metricIndex()]}/24 hourly measurements available.`:'No historical records in this date range.';const circle=$('inspected-chart-point');if(circle&&plot&&row&&Number.isFinite(row.values[metricIndex()])){circle.setAttribute('cx',plot.x(Date.parse(row.date+'T00:00:00Z')));circle.setAttribute('cy',plot.y(row.values[metricIndex()]));circle.setAttribute('visibility','visible');}else if(circle)circle.setAttribute('visibility','hidden');if(reveal&&row)showChartTooltip(row);$('daily-measurements').replaceChildren();if(row)for(let i=0;i<manifest.fields.length;i++){const item=manifest.fields[i];$('daily-measurements').append(node('dt',`${item.label} · ${item.aggregation.replace('_complete','').replaceAll('_',' ')}`),node('dd',`${format(row.values[i])}${row.values[i]!=null?' '+item.unit:''} (${row.valid[i]}/24)`));}}
  function renderTable(){const target=$('history-records');target.replaceChildren();const ordered=[...filtered].reverse(),rows=ordered.slice(page*25,page*25+25);const indices=['temp_c','precip_mm','sm_27_81','hotspots_in_cell_24h'].map(key=>manifest.fields.findIndex(field=>field.key===key));for(const row of rows){const tr=node('tr'),date=node('td'),button=node('button',row.date);button.type='button';button.onclick=()=>{pinDay(filtered.indexOf(row));$('history-chart').focus({preventScroll:true});};date.append(button);tr.append(date,...indices.map(index=>node('td',format(row.values[index]))),node('td',`${row.hours}/24`));target.append(tr);}if(!rows.length){const tr=node('tr'),td=node('td','No daily records in this date range.');td.colSpan=6;tr.append(td);target.append(tr);}$('history-page').textContent=filtered.length?`${page*25+1}–${Math.min(page*25+25,filtered.length)} of ${filtered.length.toLocaleString()} days`:'No records';$('history-prev').disabled=page===0;$('history-next').disabled=(page+1)*25>=filtered.length;}
  async function load(){const ticket=++loadVersion;cache.clear();$('analytics-status').textContent='Loading historical measurements…';$('analytics-reload').disabled=true;try{const response=await fetch('assets/historical/manifest.json',{cache:'no-store'});if(!response.ok)throw new Error(`Dataset request failed (${response.status})`);const data=await response.json();if(ticket!==loadVersion)return;if(!data.points?.length||!data.fields?.length)throw new Error('Historical dataset is incomplete');manifest=data;await loadLatestRisks();$('export-points').disabled=false;$('province-filter').replaceChildren(node('option','All five provinces'));$('province-filter').firstChild.value='';for(const province of [...new Set(data.points.map(p=>p.province))].sort()){const option=node('option',province);option.value=province;$('province-filter').append(option);}$('measurement').replaceChildren();data.fields.forEach((field,index)=>{const option=node('option',`${field.label} (${field.unit})`);option.value=index;$('measurement').append(option);});const start=data.points.map(p=>p.start).sort()[0],end=data.points.map(p=>p.end).sort().at(-1),hours=data.points.reduce((sum,p)=>sum+p.hours,0);$('analytics-kpis').replaceChildren();for(const [value,label] of [[data.points.length,'Monitoring points'],[new Set(data.points.map(p=>p.province)).size,'Kalimantan provinces'],[hours.toLocaleString(),'Historical hourly records'],[`${start.slice(0,7)} → ${end.slice(0,7)}`,'Available date range · UTC']]){const card=node('div',null,'analytics-kpi');card.append(node('strong',String(value)),node('span',label));$('analytics-kpis').append(card);}$('analytics-status').textContent=`Historical input data · ${start} to ${end} UTC · Select a point to inspect its records.`;$('analytics-provenance').textContent=`Source: ${data.source}. ${data.note}`;showPoints();renderPoints();const requested=new URLSearchParams(window.location.search).get('cell');if(requested){const point=data.points.find(item=>item.cell_id===requested);if(point)await choose(point);else $('analytics-status').textContent='That monitoring point is unavailable. Choose a point from the list.';}}catch(error){$('analytics-status').textContent=`Could not load analytics: ${error.message}`;$('analytics-kpis').replaceChildren();$('points-list').replaceChildren();$('history-chart').replaceChildren();$('history-records').replaceChildren();$('daily-measurements').replaceChildren();$('point-statistics').replaceChildren();$('day-reading').textContent='Measurements unavailable. Refresh to retry.';$('export-history').disabled=true;$('export-points').disabled=true;}finally{$('analytics-reload').disabled=false;}}
  function download(name,rows){const quote=value=>'"'+String(value??'').replaceAll('"','""')+'"';const blob=new Blob(['\uFEFF'+rows.map(row=>row.map(quote).join(',')).join('\r\n')],{type:'text/csv;charset=utf-8'});const url=URL.createObjectURL(blob),link=node('a');link.href=url;link.download=name;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
  for(const id of ['point-search','province-filter','point-sort'])$(id).addEventListener('input',()=>{if(manifest)renderPoints();});
  for(const id of ['measurement','history-from','history-to'])$(id).addEventListener('change',()=>{if(selected&&allRows.length)renderHistory();});
  $('history-prev').onclick=()=>{page=Math.max(0,page-1);renderTable();};$('history-next').onclick=()=>{page++;renderTable();};

  function showChartTooltip(row){
    const tooltip=$('chart-tooltip'),field=manifest.fields[metricIndex()];
    tooltip.replaceChildren(node('strong',`${row.date} ? UTC`),node('span',`${field.label}: ${format(row.values[metricIndex()])}${row.values[metricIndex()]!=null?' '+field.unit:''}`));
    const stats=node('dl');
    for(const key of ['temp_c','precip_mm','sm_27_81','hotspots_in_cell_24h']){
      const index=manifest.fields.findIndex(field=>field.key===key),meta=manifest.fields[index];
      stats.append(node('dt',meta.label),node('dd',`${format(row.values[index])}${row.values[index]!=null?' '+meta.unit:''}`));
    }
    tooltip.append(stats,node('small',`${row.valid[metricIndex()]}/24 hourly samples ? ${field.aggregation.replace('_complete','').replaceAll('_',' ')}`));
    tooltip.hidden=false;

  }
  function updatePinStatus(){
    $('chart-pin-status').textContent=dayPinned?`Pinned: ${filtered[inspection]?.date || ''} UTC`:'Hover to explore. Click to pin a day.';
    $('chart-unpin').hidden=!dayPinned;
    $('history-chart').classList.toggle('day-pinned',dayPinned);
  }
  function setDayPinned(value){dayPinned=value;updatePinStatus();}
  function pinDay(index){inspection=index;setDayPinned(true);inspect(index,true);}
  $('chart-unpin').onclick=()=>{setDayPinned(false);$('chart-tooltip').hidden=true;};
  function inspectPointer(event,pin=false){
    if(!plot||!filtered.length)return;
    const chart=$('history-chart'),point=chart.createSVGPoint();point.x=event.clientX;point.y=event.clientY;
    const matrix=chart.getScreenCTM();if(!matrix)return;
    const xx=point.matrixTransform(matrix.inverse()).x;
    const ts=plot.first+Math.max(0,Math.min(1,(xx-56)/676))*(plot.last-plot.first);
    let nearest=0;for(let i=1;i<plot.dates.length;i++)if(Math.abs(plot.dates[i]-ts)<Math.abs(plot.dates[nearest]-ts))nearest=i;
    if(pin)pinDay(nearest);else inspect(nearest,true);
  }
  $('history-chart').addEventListener('pointermove',event=>{if(!dayPinned)inspectPointer(event);});
  $('history-chart').addEventListener('click',event=>inspectPointer(event,true));
  $('history-chart').addEventListener('pointerleave',()=>{if(!dayPinned)$('chart-tooltip').hidden=true;});
  $('history-chart').addEventListener('focus',()=>{if(filtered.length)inspect(inspection,true);});
  $('history-chart').addEventListener('blur',()=>{if(!dayPinned)$('chart-tooltip').hidden=true;});
  $('history-chart').addEventListener('keydown',event=>{
    if(event.key==='Escape'){setDayPinned(false);$('chart-tooltip').hidden=true;return;}
    if((event.key==='Enter'||event.key===' ')&&filtered.length){event.preventDefault();if(dayPinned){setDayPinned(false);}else pinDay(inspection);return;}
    if(!filtered.length)return;
    let next=inspection;
    if(event.key==='ArrowLeft')next--;
    else if(event.key==='ArrowRight')next++;
    else if(event.key==='Home')next=0;
    else if(event.key==='End')next=filtered.length-1;
    else return;
    event.preventDefault();inspect(Math.max(0,Math.min(next,filtered.length-1)),true);
  });
  for(const button of document.querySelectorAll('[data-range]'))button.onclick=()=>{if(!selected)return;const end=new Date(selected.end+'T00:00:00Z');if(button.dataset.range!=='all')end.setUTCDate(end.getUTCDate()-Number(button.dataset.range)+1);$('history-to').value=selected.end;$('history-from').value=button.dataset.range==='all'?selected.start:[selected.start,end.toISOString().slice(0,10)].sort().at(-1);renderHistory();};
  $('export-points').onclick=()=>{if(manifest)download('kalimantan-historical-point-summary.csv',[['cell_id','province','lat','lon','peat_fraction','start_utc','end_utc','historical_hours','mean_temp_c','mean_sm_27_81'],...visiblePoints().map(p=>[p.cell_id,p.province,p.lat,p.lon,p.peat_fraction,p.start,p.end,p.hours,p.mean_temp_c,p.mean_sm_27_81])]);};
  $('export-history').onclick=()=>{if(manifest&&selected)download(`${selected.cell_id}-historical-daily.csv`,[['cell_id','date_utc','available_hours',...manifest.fields.map(f=>`${f.key} (${f.unit}; ${f.aggregation})`),...manifest.fields.map(f=>`${f.key}_valid_hours`)],...filtered.map(row=>[selected.cell_id,row.date,row.hours,...row.values,...row.valid])]);};
  function showPoints(){
    ++loadVersion;
    setDayPinned(false);selected=null;allRows=[];filtered=[];plot=null;
    $('point-explorer').hidden=true;
    document.querySelector('.points-panel').hidden=false;
    $('analytics-main').classList.remove('showing-point');
    if(manifest)renderPoints();
  }
  $('back-to-points').onclick=()=>{const cell=selected?.cell_id;const url=new URL(window.location.href);url.searchParams.delete('cell');window.history.replaceState(null,'',url);showPoints();const button=[...document.querySelectorAll('#points-list button')].find(item=>item.textContent===cell);if(button)button.focus();};
  $('analytics-reload').onclick=load;load();
})();
