/* One game loop; all state is local to this isolated mini-game. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const valve=$('valve'), hose=$('hose'), spray=$('waterSpray'), foliage=$('foliage');
  const flames=[...document.querySelectorAll('.flame')], input=$('hose-aim');
  document.querySelector('.tree').append($('flames'));
  let water=false,angle=0,intensity=100,won=false,dragging=false;
  function pivot(){const bounds=document.querySelector('.hose-container').getBoundingClientRect();return {x:bounds.left,y:bounds.bottom-30};}
  function aimError(){const base=pivot(),target=foliage.getBoundingClientRect();const targetAngle=Math.atan2(target.top+target.height/2-base.y,target.left+target.width/2-base.x)*180/Math.PI;return Math.abs(angle-targetAngle);}
  function status(){
    valve.classList.toggle('on',water);valve.setAttribute('aria-pressed',String(water));
    valve.setAttribute('aria-label',water?'Turn water off':'Turn water on');
    spray.classList.toggle('active',water&&!won);
    $('aim-status').textContent=won?'Tree saved. Play again when you are ready.':!water?'Water is off. Turn the valve to begin.':aimError()<=14?'On target! Keep the water flowing.':'Water is on. Aim the hose toward the tree.';
  }
  function setAngle(value){angle=Math.max(-85,Math.min(25,value));input.value=String(angle);hose.style.transform=`rotate(${angle}deg)`;status();}
  function paint(){
    $('progressFill').style.width=`${intensity}%`;
    $('progressLabel').textContent=`Game fire intensity: ${intensity}%`;
    $('fire-meter').setAttribute('aria-valuenow',String(intensity));
    flames.forEach((flame,index)=>flame.classList.toggle('active',intensity>[0,35,65][index]));
    foliage.classList.toggle('burning',intensity>0);
  }
  function reset(){water=false;angle=0;intensity=100;won=false;dragging=false;input.disabled=false;valve.disabled=false;$('winMessage').classList.remove('show');setAngle(0);paint();}
  valve.addEventListener('click',()=>{if(won)return;water=!water;status();});
  input.addEventListener('input',()=>{if(!won)setAngle(Number(input.value));});
  function point(event){const base=pivot();setAngle(Math.atan2(event.clientY-base.y,event.clientX-base.x)*180/Math.PI);}
  hose.addEventListener('pointerdown',event=>{if(won)return;dragging=true;hose.setPointerCapture(event.pointerId);point(event);});
  hose.addEventListener('pointermove',event=>{if(dragging&&!won)point(event);});
  for(const type of ['pointerup','pointercancel','lostpointercapture'])hose.addEventListener(type,()=>{dragging=false;});
  $('reset-game').addEventListener('click',()=>{reset();valve.focus();});
  const loop=setInterval(()=>{
    if(document.hidden||won||!water||aimError()>14)return;
    intensity=Math.max(0,intensity-2);paint();
    if(intensity===0){won=true;water=false;input.disabled=true;valve.disabled=true;status();$('winMessage').classList.add('show');$('reset-game').focus();}
  },100);
  window.addEventListener('resize',status);
  window.addEventListener('pagehide',()=>clearInterval(loop),{once:true});
  document.addEventListener('keydown',event=>{if(event.key==='Escape'&&window.parent!==window){window.parent.postMessage({type:'forest-game-close'},window.location.origin);}});
  reset();
})();
