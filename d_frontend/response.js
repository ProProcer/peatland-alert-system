(() => {
  'use strict';
  const section = document.querySelector('#dispatch-section');
  section.classList.add('response-workspace');
  section.querySelector('#dispatch').hidden = true;
  section.querySelector('.dispatch-note').hidden = true;
  const root = document.createElement('div');
  root.innerHTML = `
    <div class="response-actions"><button type="button" id="response-run" class="response-primary" disabled>Generate simulated responses</button><button type="button" id="response-refresh">Refresh response data</button><span id="response-connection" role="status">Checking local engine...</span></div>
    <p id="response-feedback" role="status"></p>
    <div id="response-metrics" class="response-metrics"></div>
    <div class="response-tabs" role="tablist" aria-label="Response workspace">
      <button type="button" role="tab" id="tab-incidents" aria-controls="panel-incidents" aria-selected="true" tabindex="0">Incidents</button>
      <button type="button" role="tab" id="tab-messages" aria-controls="panel-messages" aria-selected="false" tabindex="-1">Messages & exports</button>
      <button type="button" role="tab" id="tab-analysis" aria-controls="panel-analysis" aria-selected="false" tabindex="-1">Analysis & timeline</button>
      <button type="button" role="tab" id="tab-policy" aria-controls="panel-policy" aria-selected="false" tabindex="-1">Policy & engine</button>
    </div>
    <div role="tabpanel" id="panel-incidents" aria-labelledby="tab-incidents">
      <div class="response-filters"><label>Search incidents<input id="response-search" type="search" placeholder="Cell, incident ID or rationale"></label><label>Action<select id="response-action"><option value="">All actions</option>${['DISPATCH','SMS_WARN','REWET','BRIEF','MONITOR'].map(v=>`<option>${v}</option>`).join('')}</select></label><label>Audience<select id="response-audience"><option value="">All audiences</option>${['manggala_agni','mpa','bpbd','brgm','leadership'].map(v=>`<option value="${v}">${v.replaceAll('_',' ')}</option>`).join('')}</select></label></div>
      <div class="response-split"><div id="response-list" class="response-list" aria-label="Simulated incidents"></div><div id="response-detail" class="response-detail" aria-live="polite"></div></div>
    </div>
    <div role="tabpanel" id="panel-messages" aria-labelledby="tab-messages" hidden>
      <div class="response-filters"><label>Language<select id="response-language"><option value="en">English</option><option value="id">Bahasa Indonesia</option></select></label><label>Preview<select id="response-preview"><option value="audience">Audience messages</option><option value="twitter">Twitter / X</option><option value="facebook">Facebook</option><option value="email">Individual email</option><option value="batch">Batch email summary</option></select></label></div>
      <p class="subtle">Previews follow the incident selected in the Incidents tab. Exports include the complete response snapshot.</p>
      <div id="response-message" class="response-message"></div>
      <div class="response-downloads">${[['dispatch','Dispatch JSON'],['csv','Spreadsheet CSV'],['summary','Summary JSON'],['timeline','Timeline JSON'],['social','Social posts JSON'],['email','Email summary JSON']].map(([id,label])=>`<button type="button" data-export="${id}">${label}</button>`).join('')}</div>
      <p class="subtle">Downloads only. No SMS, email or social post is sent or published.</p>
    </div>
    <div role="tabpanel" id="panel-analysis" aria-labelledby="tab-analysis" hidden>
      <div class="response-analysis">
        <div><h3>Response breakdown</h3><div id="response-breakdown"></div></div>
        <div>
          <div class="timeline-section-heading"><h3>Incident timeline</h3><span id="timeline-count" class="small-chip"></span></div>
          <p class="timeline-help">Times are UTC. Risk badges show the latest available forecast for each point, not a recorded incident-time risk.</p>
          <div id="response-timeline" class="response-timeline"></div>
        </div>
      </div>
    </div>
    <div role="tabpanel" id="panel-policy" aria-labelledby="tab-policy" hidden>
      <div class="response-analysis"><div><h3>Dispatch policy</h3><ul class="response-rules"><li><strong>Critical or high</strong> Immediately dispatch to all five audiences.</li><li><strong>Adjacent critical cells</strong> One cluster incident at the mean center, plus a leadership brief.</li><li><strong>High risk</strong> Dispatch regardless of the deep soil moisture trend.</li><li><strong>Moderate / low</strong> No action.</li></ul><p class="subtle">Highest risk horizon drives each cell's response. A rerun reuses active incidents within cooldown; escalation and cluster changes create a new incident.</p></div>
      <div><h3>Simulation settings</h3><div class="response-settings"><label>Cooldown (hours)<input id="response-cooldown" type="number" min="0" max="168" value="6" step="0.5"></label><label>Maximum water distance (km)<input id="response-water" type="number" min="0" max="100" value="15" step="0.5"></label><label class="response-check"><input id="response-llm" type="checkbox"> Optional LLM message rephrasing</label></div><p class="subtle">Zero disables the distance cutoff. LLM rewrites must preserve facts, audience, simulation labels and the 160-character MPA limit; rejected rewrites fall back to templates.</p><div id="response-engine"></div></div></div>
      <details><summary>Simulated notification log</summary><pre id="response-log">No notification log supplied.</pre></details>
    </div>`;
  section.append(root);
  const $ = id => document.getElementById(id);
  const el = (tag,text,cls) => {const node=document.createElement(tag);if(text!=null)node.textContent=text;if(cls)node.className=cls;return node;};
  let records=[], bundle=null, online=false, selected=null, snapshot=null, version=0;
  const titles={manggala_agni:'Manggala Agni',mpa:'MPA',bpbd:'BPBD',brgm:'BRGM',leadership:'Leadership'};
  function summary(){const by_action={},by_priority={},by_audience={};for(const row of records){by_action[row.action]=(by_action[row.action]||0)+1;by_priority[row.priority]=(by_priority[row.priority]||0)+1;for(const a of row.audiences)by_audience[a]=(by_audience[a]||0)+1;}return {total_dispatches:records.length,by_action,by_priority,by_audience,cells_affected:new Set(records.map(r=>r.cell_id)).size,with_water_source:records.filter(r=>r.water_source).length,without_water_source:records.filter(r=>!r.water_source).length};}
  function timeline(){return [...records].sort((a,b)=>Date.parse(a.ts)-Date.parse(b.ts)).map(({ts,dispatch_id,cell_id,action,priority,audiences})=>({ts,dispatch_id,cell_id,action,priority,audiences}));}
  function current(){return records.find(r=>r.dispatch_id===selected);}
  function render(){
    if(!records.some(r=>r.dispatch_id===selected))selected=records[0]?.dispatch_id;
    const stats=summary();$('response-metrics').replaceChildren();
    for(const [label,value] of [['Response records',records.length],['Primary incident cells',stats.cells_affected],['Priority 1',stats.by_priority[1]||0],['With water source',stats.with_water_source]]){const card=el('div',null,'response-metric');card.append(el('strong',String(value)),el('span',label));$('response-metrics').append(card);}
    renderList();renderDetail();renderMessage();
    $('response-breakdown').replaceChildren();
    for(const [title,counts] of [['Actions',stats.by_action],['Priorities',stats.by_priority],['Audiences',stats.by_audience]]){const group=el('div',null,'response-counts');group.append(el('h4',title));for(const [key,count] of Object.entries(counts)){const row=el('div');row.append(el('span',titles[key]||key.replaceAll('_',' ')),el('strong',`${count} · ${records.length?(100*count/records.length).toFixed(0):0}%`));group.append(row);}$('response-breakdown').append(group);}
    $('response-breakdown').append(el('p',`Without water source: ${stats.without_water_source}. Counts refer to actions and primary cells; cluster member totals are not supplied in dispatch schema 1.0. Audience percentages may overlap.`,'subtle'));
    renderTimeline();
    $('response-engine').replaceChildren();const engine=bundle?.engine;for(const text of [online?'Local simulation engine connected':'Static view · generation requires the local demo server',engine?.water_available?`Water catalogue connected: ${engine.water_catalogue || 'dataset catalogue'}`:'Water catalogue unavailable · sources remain null',engine?.spatial_water?'Spatial water lookup available':'JSON water lookup supported; spatial lookup requires its dependencies',engine?.llm_available?'LLM credentials configured · rewrites remain validated':'No LLM credentials configured · deterministic templates',engine?.state_persisted?'Incident state saved · dedupe enabled':'Incident state will be created on first run'])$('response-engine').append(el('p',text,'engine-line'));
    $('response-log').textContent=bundle?.log?.join('\n')||'No simulated notification log available.';
    $('response-llm').disabled=!online||!engine?.llm_available;
    for(const button of root.querySelectorAll('[data-export]'))button.disabled=['social','email'].includes(button.dataset.export)&&!bundle;
  }
  function renderTimeline(){
    const container=$('response-timeline');container.replaceChildren();
    $('timeline-count').textContent=`${records.length} events`;
    if(!records.length){container.append(el('p','No incidents in this response snapshot.','response-empty'));return;}
    const actionNames={DISPATCH:'Team dispatch',BRIEF:'Leadership brief',SMS_WARN:'Community warning',REWET:'Rewetting response',MONITOR:'Monitoring update'};
    const riskColors={LOW:'#32945b',MODERATE:'#bd881a',HIGH:'#d27632',CRITICAL:'#c34848'};
    let previousDay=null,list=null;
    for(const row of timeline()){
      const date=new Date(row.ts),day=row.ts.slice(0,10);
      if(day!==previousDay){
        const heading=el('h4',new Intl.DateTimeFormat('en-GB',{day:'numeric',month:'long',year:'numeric',timeZone:'UTC'}).format(date),'timeline-date');
        container.append(heading);list=el('ol',null,'timeline-events');container.append(list);previousDay=day;
      }
      const candidates=(snapshot?.risk||[]).filter(item=>item.cell_id===row.cell_id).sort((a,b)=>Date.parse(b.ts)-Date.parse(a.ts)||b.risk_score-a.risk_score||a.horizon_h-b.horizon_h);
      const risk=candidates[0];
      const entry=el('li',null,'timeline-entry');entry.style.setProperty('--event-color',riskColors[risk?.risk_level]||'#8b9484');
      const card=el('article',null,'timeline-card');
      const top=el('div',null,'timeline-card-heading'),action=el('h5',actionNames[row.action]||row.action.replaceAll('_',' '));
      const badge=el('span',risk?risk.risk_level:'Risk unavailable',`timeline-risk ${risk?.risk_level||'unavailable'}`);
      if(risk)badge.title=`Latest forecast: ${(risk.risk_score*100).toFixed(1)}% / ${risk.horizon_h}h / ${risk.ts}`;
      top.append(action,badge);
      const point=el('strong',row.cell_id,'timeline-cell');
      const time=el('time',new Intl.DateTimeFormat('en-GB',{hour:'2-digit',minute:'2-digit',hourCycle:'h23',timeZone:'UTC'}).format(date)+' UTC','timeline-time');time.dateTime=row.ts;
      const meta=el('div',null,'timeline-card-meta');meta.append(point,time);
      const audiences=el('div',null,'timeline-recipients');audiences.setAttribute('aria-label','Response audiences');
      for(const audience of row.audiences)audiences.append(el('span',titles[audience]||audience));
      const link=el('button','View response','timeline-view');link.type='button';link.setAttribute('aria-label',`View ${actionNames[row.action]||row.action} for ${row.cell_id}`);
      link.onclick=()=>{selected=row.dispatch_id;activate($('tab-incidents'));renderList();renderDetail();renderMessage();$('response-detail').scrollIntoView({block:'nearest',behavior:'instant'});$('tab-incidents').focus({preventScroll:true});};
      card.append(top,meta,audiences,link);entry.append(card);list.append(entry);
    }
  }
  function renderList(){const query=$('response-search').value.toLowerCase(),action=$('response-action').value,audience=$('response-audience').value;const filtered=records.filter(r=>(!action||r.action===action)&&(!audience||r.audiences.includes(audience))&&`${r.cell_id} ${r.dispatch_id} ${r.rationale}`.toLowerCase().includes(query));$('response-list').replaceChildren();for(const row of filtered){const button=el('button',null,'response-incident');button.type='button';button.setAttribute('aria-pressed',String(row.dispatch_id===selected));button.append(el('span',row.action.replaceAll('_',' '),'response-action-label'),el('strong',row.cell_id));button.onclick=()=>{selected=row.dispatch_id;renderList();renderDetail();renderMessage();};$('response-list').append(button);}if(!filtered.length)$('response-list').append(el('p',records.length?'No incidents match these filters.':'No response records. Generate simulated responses from the current forecasts, or refresh an existing dispatch feed.','response-empty'));}
  function renderDetail(){
    const row=current(),target=$('response-detail');
    target.replaceChildren();
    if(!row){target.append(el('p','Select an incident to view its location and response.','response-empty'));return;}
    const actions={DISPATCH:'Dispatch team',BRIEF:'Leadership brief',SMS_WARN:'Community warning',REWET:'Rewetting response',MONITOR:'Monitor area'};
    target.append(el('h3',actions[row.action]||row.action.replaceAll('_',' ')));
    const water=row.water_source;
    const facts=el('table',null,'response-facts-table');
    facts.setAttribute('aria-label','Dispatch details');
    const body=el('tbody');
    for(const [label,value] of [
      ['Monitoring point',row.cell_id],
      ['Location',`${Number(row.target.lat).toFixed(4)}, ${Number(row.target.lon).toFixed(4)}`],
      ['Nearest water',water?water.kind:'No mapped source within range'],
      ['Water distance',water?`${Number(water.distance_km).toFixed(1)} km`:'Unavailable']
    ]){
      const tr=el('tr'),th=el('th',label);th.scope='row';
      tr.append(th,el('td',value));body.append(tr);
    }
    facts.append(body);target.append(facts);
    const button=el('button','Locate monitoring cell on map');
    button.type='button';
    button.onclick=()=>window.dispatchEvent(new CustomEvent('locate-monitoring-cell',{detail:{cellId:row.cell_id}}));
    target.append(button);
    const more=el('details',null,'response-technical');
    more.append(el('summary','More details'));
    const technical=el('table',null,'response-facts-table response-technical-table');
    technical.setAttribute('aria-label','Additional dispatch details');
    const technicalBody=el('tbody');
    function addDetail(label,value){
      const tr=el('tr'),th=el('th',label),td=el('td');th.scope='row';
      if(Array.isArray(value)){for(const line of value)td.append(el('div',line));}
      else td.textContent=value;
      tr.append(th,td);technicalBody.append(tr);
    }
    addDetail('Dispatch ID',row.dispatch_id);
    addDetail('Priority',String(row.priority));
    addDetail('Status',row.status);
    addDetail('Created (UTC)',row.ts);
    addDetail('Audiences',row.audiences.map(a=>titles[a]||a));
    const risk=(snapshot?.risk||[]).filter(item=>item.cell_id===row.cell_id).sort((a,b)=>b.risk_score-a.risk_score||a.horizon_h-b.horizon_h)[0];
    if(risk){
      addDetail('Current risk',`${risk.risk_level} (${(risk.risk_score*100).toFixed(1)}%)`);
      addDetail('Forecast window',`${risk.horizon_h} hours`);
      addDetail('Forecast time (UTC)',risk.ts);
      addDetail('Model',risk.model_version);
      if(risk.top_factors?.length)addDetail('Model factors',risk.top_factors.map(f=>`${f.feature.replaceAll('_',' ')}: ${f.contribution>=0?'+':''}${Number(f.contribution).toFixed(3)}`));
    }
    if(water){
      addDetail('Water coordinates',`${Number(water.lat).toFixed(4)}, ${Number(water.lon).toFixed(4)}`);
      addDetail('Water access','Availability and access unverified');
    }
    technical.append(technicalBody);more.append(technical);
    target.append(more);
  }
  function renderMessage(){const target=$('response-message');target.replaceChildren();const row=current(),language=$('response-language').value,kind=$('response-preview').value;if(kind==='batch'){if(bundle){target.append(el('h3',bundle.email.subject[language]),el('pre',bundle.email.body[language]));}else target.append(el('p','Connect the local engine to generate email templates.'));return;}if(!row){target.append(el('p','Select an incident to preview its messages.','response-empty'));return;}if(kind==='audience'){for(const audience of row.audiences){const text=row.messages[audience][language];const card=el('article',null,'audience-message');card.append(el('h3',titles[audience]),el('p',text));if(audience==='mpa')card.append(el('small',`${text.length}/160 characters · ${text.length<=160?'Within SMS limit':'Exceeds SMS limit'}`));target.append(card);}}else if(!bundle){target.append(el('p','Start the local demo server to generate social and email previews.'));}else if(kind==='email'){const email=bundle.individual_emails.find(r=>r.dispatch_id===row.dispatch_id);if(email)target.append(el('h3',email.subject[language]),el('pre',email.body[language]));}else{const index=bundle.dispatches.findIndex(r=>r.dispatch_id===row.dispatch_id);const text=bundle.social[kind][index]?.[language];target.append(el('p',text||'Preview unavailable.'));if(kind==='twitter'&&text)target.append(el('small',`${text.length}/280 characters`));}}
  async function refresh(){const ticket=++version;try{const response=await fetch('/response/status',{cache:'no-store'});if(!response.ok)throw new Error('Local engine unavailable');const data=await response.json();if(ticket!==version)return;const ids=new Set(snapshot?.features?.map(r=>r.cell_id)||[]);if(data.dispatches.some(r=>!ids.has(r.cell_id)))throw new Error('Response feed refers to different monitoring cells');bundle=data;records=data.dispatches;online=true;$('response-connection').textContent='Local engine connected · simulation only';}catch(error){if(ticket!==version)return;bundle=null;online=false;records=snapshot?.dispatch||[];$('response-connection').textContent='Saved snapshot · local engine unavailable';}$('response-run').disabled=!online;render();}
  window.addEventListener('response-feeds',event=>{snapshot=event.detail;records=snapshot.dispatch||[];render();refresh();});
  $('response-refresh').onclick=refresh;
  $('response-run').onclick=async()=>{const cooldown=$('response-cooldown'),water=$('response-water');if(!cooldown.reportValidity()||!water.reportValidity())return;const button=$('response-run');button.disabled=true;$('response-feedback').textContent='Generating simulated responses...';try{const response=await fetch('/response/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({cooldown_hours:Number(cooldown.value),max_water_km:Number(water.value),use_llm:$('response-llm').checked})});const data=await response.json();if(!response.ok)throw new Error(data.error||'Generation failed');bundle=data;records=data.dispatches;render();$('response-feedback').textContent=`Updated ${records.length} response records. Notifications remain simulated.`;window.dispatchEvent(new Event('refresh-dashboard'));}catch(error){$('response-feedback').textContent=`Could not generate responses: ${error.message}`;}finally{button.disabled=!online;}};
  for(const id of ['response-search','response-action','response-audience'])$(id).addEventListener('input',renderList);
  for(const id of ['response-language','response-preview'])$(id).addEventListener('change',renderMessage);
  const tabs=[...root.querySelectorAll('[role=tab]')];function activate(tab){for(const item of tabs){const active=item===tab;item.setAttribute('aria-selected',String(active));item.tabIndex=active?0:-1;$(item.getAttribute('aria-controls')).hidden=!active;}}
  tabs.forEach((tab,index)=>{tab.onclick=()=>activate(tab);tab.onkeydown=event=>{let next;if(event.key==='ArrowRight')next=(index+1)%tabs.length;if(event.key==='ArrowLeft')next=(index+tabs.length-1)%tabs.length;if(event.key==='Home')next=0;if(event.key==='End')next=tabs.length-1;if(next!=null){event.preventDefault();activate(tabs[next]);tabs[next].focus();}};});
  for(const button of root.querySelectorAll('[data-export]'))button.onclick=()=>{const kind=button.dataset.export;let value,type='application/json',extension='json';if(kind==='dispatch')value=records;if(kind==='summary')value=summary();if(kind==='timeline')value=timeline();if(kind==='social')value=bundle?.social;if(kind==='email')value=bundle?.email;if(kind==='csv'){const columns=['dispatch_id','cell_id','ts','action','priority','lat','lon','audiences','water_source_kind','water_source_distance_km'];const quote=v=>'"'+String(v??'').replaceAll('"','""')+'"';value=[columns,...records.map(r=>[r.dispatch_id,r.cell_id,r.ts,r.action,r.priority,r.target.lat,r.target.lon,r.audiences.join(','),r.water_source?.kind,r.water_source?.distance_km])].map(row=>row.map(quote).join(',')).join('\r\n');type='text/csv';extension='csv';}if(value==null)return;const url=URL.createObjectURL(new Blob([extension==='json'?JSON.stringify(value,null,2):value],{type}));const link=document.createElement('a');link.href=url;link.download=`simulated-${kind}.${extension}`;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
})();
