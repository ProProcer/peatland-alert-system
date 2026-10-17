/* Render supplied model evidence without treating heuristic factors as probabilities. */
(() => {
  'use strict';
  const metadata = {
    peat_fraction: ['Peat coverage', 'fraction'], peat_area_km2: ['Peat area', 'km²'],
    temp_c: ['Air temperature', '°C'], precip_mm: ['Hourly precipitation', 'mm'],
    wind_kmh: ['Wind speed', 'km/h'], wind_dir_deg: ['Wind direction', '°'],
    sm_0_1: ['Soil moisture · 0–1 cm', 'm³/m³'], sm_1_3: ['Soil moisture · 1–3 cm', 'm³/m³'],
    sm_3_9: ['Soil moisture · 3–9 cm', 'm³/m³'], sm_9_27: ['Soil moisture · 9–27 cm', 'm³/m³'],
    sm_27_81: ['Deep soil moisture · 27–81 cm', 'm³/m³'], vpd_kpa: ['Vapour pressure deficit', 'kPa'],
    soil_temp_0_c: ['Surface soil temperature', '°C'], soil_temp_18_c: ['Soil temperature · 18 cm', '°C'],
    et_mm: ['Evapotranspiration', 'mm'], et0_mm: ['Reference evapotranspiration', 'mm'],
    rain_24h_mm: ['Rainfall · 24 hours', 'mm'], rain_7d_mm: ['Rainfall · 7 days', 'mm'],
    rain_30d_mm: ['Rainfall · 30 days', 'mm'], days_since_rain: ['Days since rain', 'days'],
    sm_27_81_delta_7d: ['Deep moisture change · 7 days', 'm³/m³'],
    vpd_mean_24h: ['Mean vapour pressure deficit · 24 hours', 'kPa'], soil_air_temp_gap_c: ['Soil–air temperature gap', '°C'],
    hotspots_in_cell_24h: ['Hotspots in cell · 24 hours', 'count'], hotspots_10km_7d: ['Nearby hotspots · 7 days', 'count'],
    frp_sum_10km_7d: ['Nearby fire radiative power · 7 days', 'MW'], nearest_hotspot_km: ['Nearest hotspot distance', 'km'],
  };
  function measurement(feature, name) {
    const entry = metadata[name] || [name.replaceAll('_', ' '), ''];
    let value = null;
    for (const group of ['peat','weather','derived','fire']) if (feature?.[group] && name in feature[group]) value = feature[group][name];
    return { name: entry[0], raw: value, text: value == null ? 'Unavailable · saved-model imputation may apply' : `${Number(value).toLocaleString('en-US', {maximumFractionDigits: 4})} ${entry[1]}`.trim() };
  }
  function explanation(feature, risk, horizon) {
    const factors = (risk?.top_factors || []).filter(row => Number.isFinite(row.contribution));
    const largest = Math.max(...factors.map(row => Math.abs(row.contribution)), 0);
    return { horizon, risk, factors: factors.map(row => ({ ...row, ...measurement(feature, row.feature),
      direction: row.contribution > 0 ? 'Positive model factor' : row.contribution < 0 ? 'Negative model factor' : 'Neutral model factor',
      width: largest ? Math.abs(row.contribution) / largest * 100 : 0 })) };
  }
  function fitWindow(bounds, rect) {
    const width=Math.min(Math.max(280,rect.width),Math.max(0,bounds.width-20));
    const height=Math.min(Math.max(220,rect.height),Math.max(0,bounds.height-20));
    return {width,height,left:Math.max(10,Math.min(rect.left,bounds.width-width-10)),top:Math.max(10,Math.min(rect.top,bounds.height-height-10))};
  }
  if (typeof module !== 'undefined' && module.exports) { module.exports = {measurement, explanation, fitWindow}; return; }
  const stage = document.querySelector('.map-stage');
  const popup = document.createElement('section');
  popup.id = 'cell-explanation'; popup.className = 'cell-explanation'; popup.hidden = true;
  popup.setAttribute('role','dialog'); popup.setAttribute('aria-modal','false');
  popup.setAttribute('aria-labelledby','cell-explanation-title'); popup.tabIndex = -1;
  stage.append(popup);
  let selection = null;
  let placed = false, gesture = null;
  const element = (tag, text, cls) => { const node=document.createElement(tag); if(text!=null)node.textContent=text;if(cls)node.className=cls;return node; };
  function stopGesture() {
    if(!gesture)return;
    const {handle,id}=gesture;gesture=null;
    if(handle.hasPointerCapture(id))handle.releasePointerCapture(id);
    popup.classList.remove('is-adjusting');
  }
  function close(restore=false) { stopGesture();popup.hidden=true; if(restore && selection?.anchor?.isConnected)selection.anchor.focus({preventScroll:true}); }
  function windowRect() { return {left:parseFloat(popup.style.left)||10,top:parseFloat(popup.style.top)||10,width:popup.offsetWidth,height:popup.offsetHeight}; }
  function applyRect(rect) {
    const fitted=fitWindow({width:stage.clientWidth,height:stage.clientHeight},rect);
    for(const key of ['left','top','width','height'])popup.style[key]=`${fitted[key]}px`;
  }
  function position() {
    if(popup.hidden)return;
    if(placed){applyRect(windowRect());return;}
    const bounds=stage.getBoundingClientRect(), anchor=selection?.anchor?.getBoundingClientRect();
    const left=anchor ? anchor.right-bounds.left+15 : bounds.width-popup.offsetWidth-12;
    applyRect({...windowRect(),left,top:12});
  }
  function attachHandle(handle, mode) {
    handle.addEventListener('pointerdown',event=>{
      if(event.button!==0||event.target.closest('.explain-close'))return;
      event.preventDefault();stopGesture();placed=true;
      gesture={handle,id:event.pointerId,x:event.clientX,y:event.clientY,rect:windowRect()};
      handle.setPointerCapture(event.pointerId);popup.classList.add('is-adjusting');
    });
    handle.addEventListener('pointermove',event=>{
      if(!gesture||gesture.handle!==handle||event.pointerId!==gesture.id)return;
      const {rect,x,y}=gesture, dx=event.clientX-x, dy=event.clientY-y;
      const maxWidth=stage.clientWidth-rect.left-10,maxHeight=stage.clientHeight-rect.top-10;
      applyRect(mode==='move'?{...rect,left:rect.left+dx,top:rect.top+dy}:{...rect,width:Math.min(maxWidth,rect.width+dx),height:Math.min(maxHeight,rect.height+dy)});
    });
    for(const name of ['pointerup','pointercancel','lostpointercapture'])handle.addEventListener(name,event=>{if(gesture?.id===event.pointerId)stopGesture();});
    handle.addEventListener('keydown',event=>{
      if(!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(event.key)||event.target!==handle)return;
      event.preventDefault();event.stopPropagation();placed=true;
      const rect=windowRect(),step=event.shiftKey?30:10;
      const dx=event.key==='ArrowLeft'?-step:event.key==='ArrowRight'?step:0;
      const dy=event.key==='ArrowUp'?-step:event.key==='ArrowDown'?step:0;
      applyRect(mode==='move'?{...rect,left:rect.left+dx,top:rect.top+dy}:{...rect,width:Math.min(stage.clientWidth-rect.left-10,rect.width+dx),height:Math.min(stage.clientHeight-rect.top-10,rect.height+dy)});
    });
  }
  function show(detail, focus=false) {
    stopGesture();
    selection=detail;
    const {feature,risk,horizon,id}=detail, model=explanation(feature,risk,horizon);
    popup.replaceChildren();
    const header=element('div',null,'explain-header');
    header.tabIndex=0;header.setAttribute('role','group');header.setAttribute('aria-label','Move explanation window. Drag or use arrow keys.');
    header.title='Drag to move · Arrow keys when focused';attachHandle(header,'move');
    const title=element('div');title.append(element('span','MODEL EXPLANATION','explain-eyebrow'));
    const heading=element('h3',id);heading.id='cell-explanation-title';title.append(heading);
    const dismiss=element('button','×','explain-close');dismiss.type='button';dismiss.setAttribute('aria-label','Close model explanation');dismiss.onclick=()=>close(true);
    header.append(title,dismiss);popup.append(header);
    const body=element('div',null,'explain-body');popup.append(body);
    const historyLink=element('a','View Historical Data','explain-history-link');
    historyLink.href=`analytics.html?cell=${encodeURIComponent(id)}`;
    historyLink.setAttribute('aria-label',`View historical data for monitoring point ${id}`);
    body.append(historyLink);

    if(!risk){body.append(element('p',`No ${horizon}-hour prediction supplied for this point. Model factors are unavailable.`,'explain-note'));}
    else {
      const result=element('div',null,'explain-result');result.append(element('span',risk.risk_level,`badge ${risk.risk_level}`),element('strong',`${(risk.risk_score*100).toFixed(1)}%`),element('span',`${horizon}-hour hotspot probability`));popup.append(result);
      popup.append(element('p',`Model ${risk.model_version} · ${risk.ts}`,'explain-meta'));
      const steps=element('ol',null,'explain-steps');
      for(const text of ['Weather, soil, peat and hotspot inputs describe this grid cell.', 'The saved model processes the inputs and returns a risk score for the selected horizon.', `Fixed thresholds classify this score as ${risk.risk_level}: LOW <35%, MODERATE 35–<60%, HIGH 60–<80%, CRITICAL ≥80%.`])steps.append(element('li',text));
      popup.append(steps,element('h4','Leading model factors'));
      if(!model.factors.length)popup.append(element('p','No contributing factors were supplied.','explain-note'));
      for(const factor of model.factors){const row=element('div',null,'explain-factor');const line=element('div',null,'explain-factor-heading');line.append(element('strong',factor.name),element('span',`${factor.contribution>=0?'+':''}${factor.contribution.toFixed(4)}`));const track=element('div',null,'explain-track'),bar=element('span',null,factor.contribution<0?'negative':'positive');bar.style.width=`${factor.width}%`;track.append(bar);row.append(line,track,element('small',`${factor.direction} · Input: ${factor.text}`));popup.append(row);}
      popup.append(element('p','Factors are the model’s supplied signed heuristic contributions. Bar lengths compare their magnitude; they are not percentage-point changes, causal effects, or an exact decomposition of the final probability.','explain-note'));
    }
    const inputs=document.createElement('details');inputs.append(element('summary','Inspect model input measurements'));
    const list=element('dl',null,'explain-inputs');for(const name of Object.keys(metadata)){const value=measurement(feature,name);list.append(element('dt',value.name),element('dd',value.text));}inputs.append(list);popup.append(inputs);
    popup.append(element('p',`Feature snapshot: ${feature?.ts || 'unavailable'}. Weather and soil are modeled. Prediction concerns surface hotspot emergence, not confirmed fire.`,'explain-note'));
    // Keep the header and resize grip visible while the explanation scrolls.
    for(const child of [...popup.children])if(child!==header&&child!==body)body.append(child);
    const footer=element('div',null,'explain-window-tools');
    footer.append(element('span','Drag header to move · Drag corner to resize'));
    const grip=element('button','◢','explain-resize');grip.type='button';
    grip.setAttribute('aria-label','Resize explanation window. Drag or use arrow keys.');grip.title='Drag to resize · Arrow keys when focused';
    attachHandle(grip,'resize');footer.append(grip);popup.append(footer);
    popup.hidden=false;position();if(focus)popup.focus({preventScroll:true});
  }
  window.addEventListener('close-cell-explanation',()=>close());
  window.addEventListener('cell-explain',event=>show(event.detail,event.detail.keyboard));
  document.querySelector('#horizon').addEventListener('change',()=>{
    if(popup.hidden||!selection)return;
    const horizon=Number(document.querySelector('#horizon').value);
    const marker=[...document.querySelectorAll('.risk-map-marker')].find(node=>node.dataset.cellId===selection.id);
    if(marker)marker.dispatchEvent(new MouseEvent('click',{bubbles:true,detail:1}));else close();
  });
  window.addEventListener('response-feeds',()=>close());
  popup.addEventListener('keydown',event=>{if(event.key==='Escape'){event.stopPropagation();close(true);}});
  document.addEventListener('keydown',event=>{if(event.key==='Escape'&&!popup.hidden)close(true);});
  document.addEventListener('pointerdown',event=>{if(!popup.hidden&&!popup.contains(event.target)&&!event.target.closest('.risk-map-marker,.map-cell,#horizon'))close();});
  window.addEventListener('resize',position);
  window.addEventListener('map-view-change',position);
  new ResizeObserver(position).observe(stage);
})();
