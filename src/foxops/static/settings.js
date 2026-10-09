"use strict";
const UI=globalThis.FoxLiveUI, $=id=>document.getElementById(id);
let state, catalogs, t, step=0, busy=false, ready=false;
document.querySelectorAll('input,select,button').forEach(node=>node.disabled=true);
let language=UI.preferred(localStorage);
const fields=['port','manual-port','baud','http-port','sync-interval','reconnect-interval','logging-level','new-folder','data-mode'];
function preference() { UI.remember(localStorage,language); }
function render() {
  t=UI.translator({en:catalogs.en,de:catalogs.de},language); document.documentElement.lang=language; $('language').value=language;
  document.querySelectorAll('[data-t]').forEach(node=>node.textContent=t(node.dataset.t));
  $('title').textContent=t(state.completed?'settings':'setup');
  document.querySelectorAll('[data-step]').forEach(node=>node.hidden=!state.completed&&Number(node.dataset.step)!==step);
  $('normal').hidden=!state.completed; $('bridge').hidden=!state.completed; $('steps').hidden=state.completed;
  $('steps').textContent=t('step',{number:step+1,total:5}); $('previous').hidden=state.completed||step===0;
  $('next').hidden=state.completed||step===4; $('finish').hidden=!state.completed&&step!==4;
  $('finish').textContent=t(state.completed?'save':'finish'); $('override').hidden=!state.override;
  document.querySelectorAll('input,select,button').forEach(node=>node.disabled=!ready||state.override||busy);
  $('language').disabled=!ready||busy;
  $('shutdown').disabled=!ready||busy;
  if(state.suggestion){$('suggestion').textContent=t('found',{port:state.suggestion.port});$('suggestion').hidden=false;$('use-suggestion').hidden=false;}
  else {$('suggestion').hidden=!state.identity_confirmation;$('suggestion').textContent=t('identity_missing');$('use-suggestion').hidden=true;}
}
function showError(error) {$('error').textContent=error.message||String(error);$('error').hidden=false;}
async function api(path,body) {
  const response=await fetch('/api/ops/'+path,{headers:{'Accept-Language':language,...(body!==undefined?{'Content-Type':'application/json'}:{})},...(body!==undefined?{method:'POST',body:JSON.stringify(body)}:{})});
  const result=await response.json(); if(!response.ok)throw new Error(typeof result.detail==='string'?result.detail:t('invalid'));return result;
}
function action(callback){return async event=>{event?.preventDefault();if(busy)return;busy=true;render();$('error').hidden=true;try{await callback();}catch(error){showError(error);}finally{busy=false;render();}};}
function port(){return $('manual-port').value.trim()||$('port').value;}
function draft(){sessionStorage.setItem('foxops.setup',JSON.stringify(Object.fromEntries(fields.map(id=>[id,$(id).value]))));}
async function refreshPorts(){const previous=port();state=await api('settings');$('port').replaceChildren(new Option(t('choose_port'),''));for(const item of state.ports)$('port').add(new Option(item.label,item.port));if(previous&&state.ports.some(item=>item.port===previous))$('port').value=previous;else if(previous)$('manual-port').value=previous;render();}
async function backups(){const list=await api('backups');$('backups').replaceChildren(...list.map(item=>new Option(item.name,item.name)));$('restore').hidden=!list.length;$('download').hidden=!list.length;if(list.length)$('download').href='/api/ops/backups/'+encodeURIComponent($('backups').value);}
async function reconnect(url='/settings'){
  $('message').textContent=t('restarting');
  for(let attempt=0;attempt<40;attempt++){await new Promise(resolve=>setTimeout(resolve,500));try{const response=await fetch(url,{cache:'no-store'});if(response.ok&&attempt>2){location.href=url;return;}}catch{/* Owned server is restarting. */}}
  $('message').textContent=t('restart_help');
}
async function mappings(){
  const list=await api('bridge/mappings');$('bridge-mappings').replaceChildren();
  for(const [kind,items] of Object.entries(list))for(const item of items){
    const row=document.createElement('p'),label=document.createElement('span'),remove=document.createElement('button');
    label.textContent=kind==='uids'?item.uid+' → '+item.card_number+' ':item.station_id+' → '+item.control_code+' ('+item.role+') ';
    remove.type='button';remove.dataset.t='remove_mapping';remove.textContent=t('remove_mapping');
    remove.onclick=action(async()=>{await api('bridge/mappings/'+(kind==='uids'?'uid':'station')+'/remove',kind==='uids'?{uid:item.uid}:{station_id:item.station_id});await mappings();});
    row.append(label,remove);$('bridge-mappings').append(row);
  }
}
async function start(){
  catalogs=Object.fromEntries(await Promise.all(['en','de'].map(async lang=>[lang,await(await fetch('/ops/static/'+lang+'.json')).json()])));
  state=await api('settings');if(!localStorage.getItem('foxlive.language'))language=state.language;preference();render();
  $('data-location').value=state.data_directory;$('baud').value=state.baud_rate;$('http-port').value=state.http_port;$('time-sync').checked=state.time_sync;$('sync-interval').value=state.time_sync_interval;$('reconnect-interval').value=state.reconnect_interval;$('logging-level').value=state.logging_level;
  $('locations').replaceChildren(...['settings','database','logs','backups'].flatMap(key=>{const label=document.createElement('dt'),value=document.createElement('dd');label.textContent=t(key);value.textContent=state[key];return[label,value];}));
  await refreshPorts();if(state.port){if(state.ports.some(p=>p.port===state.port))$('port').value=state.port;else $('manual-port').value=state.port;}
  if(!state.completed){try{const saved=JSON.parse(sessionStorage.getItem('foxops.setup')||'null');if(saved)for(const id of fields)if(saved[id])$(id).value=saved[id];}catch{/* Optional browser storage. */}}
  if(state.last_operation&&state.last_operation!=='ok')showError(new Error(state.last_operation));
  await backups();
  const bridge=await api('bridge');$('bridge-enabled').checked=bridge.enabled;for(const [id,key] of [['bridge-target','target'],['bridge-type','output_type'],['bridge-port','port'],['bridge-baud','baud_rate'],['bridge-path','path'],['bridge-timezone','timezone'],['bridge-week','week_counter']])$(id).value=bridge[key];
  $('bridge-form').onsubmit=action(async()=>{await api('bridge',{enabled:$('bridge-enabled').checked,target:$('bridge-target').value,output_type:$('bridge-type').value,port:$('bridge-port').value,baud_rate:Number($('bridge-baud').value),path:$('bridge-path').value,timezone:$('bridge-timezone').value,week_counter:Number($('bridge-week').value)});$('message').textContent=t('bridge_saved');});
  $('language').onchange=()=>{language=$('language').value;preference();render();};
  $('previous').onclick=()=>{step=Math.max(0,step-1);render();};
  $('next').onclick=()=>{if(step===1&&!port()){showError(new Error(t('choose_port')));return;}step=Math.min(4,step+1);render();};
  $('refresh').onclick=action(refreshPorts);
  $('use-suggestion').onclick=()=>{$('port').value=state.suggestion.port;$('manual-port').value='';$('suggestion').hidden=true;$('use-suggestion').hidden=true;};
  $('port').onchange=()=>{$('manual-port').value='';};
  $('test').onclick=action(async()=>{if(!port())throw new Error(t('choose_port'));$('test-result').textContent=t('testing');const result=await api('test',{port:port(),baud_rate:Number($('baud').value)});$('test-result').textContent=result.opened?t('opened',{port:port()})+'\n'+t(result.time_sent?'time_sent':'time_failed')+'\n'+t('not_identity'):t('port_unavailable',{port:port()});});
  $('settings-form').onsubmit=action(async()=>{const result=await api('settings',{port:port(),language,http_port:Number($('http-port').value),baud_rate:Number($('baud').value),time_sync:$('time-sync').checked,time_sync_interval:Number($('sync-interval').value),reconnect_interval:Number($('reconnect-interval').value),logging_level:$('logging-level').value});sessionStorage.removeItem('foxops.setup');result.restart?await reconnect(result.url):location.assign(result.url);});
  $('browse-folder').onclick=action(async()=>{const result=await api('browse',{});if(result.directory)$('new-folder').value=result.directory;});
  $('change-data').onclick=action(async()=>{if(!confirm(t('confirm_data')))return;draft();await api('location',{directory:$('new-folder').value,mode:$('data-mode').value,confirmed:true});await reconnect(state.completed?'/settings':'/setup');});
  $('backup').onclick=action(async()=>{const result=await api('backup',{});await backups();$('message').textContent=t('backup_created');$('backups').value=result.name;$('download').href='/api/ops/backups/'+encodeURIComponent(result.name);});
  $('backups').onchange=()=>{$('download').href='/api/ops/backups/'+encodeURIComponent($('backups').value);};
  $('import-backup').onclick=action(async()=>{const file=$('import-file').files[0];if(!file)throw new Error(t('choose_backup'));const response=await fetch('/api/ops/import',{method:'POST',headers:{'Content-Type':'application/octet-stream','Accept-Language':language},body:file});const result=await response.json();if(!response.ok)throw new Error(result.detail);await backups();$('backups').value=result.name;$('backups').onchange();});
  $('restore').onclick=action(async()=>{if(!confirm(t('confirm_restore')))return;await api('restore',{name:$('backups').value,confirmed:true});await reconnect();});
  $('shutdown').onclick=action(async()=>{if(!confirm(t('confirm_shutdown')))return;await api('shutdown',{});$('message').textContent=t('stopped');document.querySelectorAll('button').forEach(node=>node.hidden=true);});
  await mappings();
  $('uid-map-form').onsubmit=action(async()=>{await api('bridge/mappings/uid',{uid:$('mapping-uid').value,card_number:Number($('mapping-card').value)});$('uid-map-form').reset();await mappings();});
  $('station-map-form').onsubmit=action(async()=>{await api('bridge/mappings/station',{station_id:Number($('mapping-station').value),control_code:Number($('mapping-control').value),role:$('mapping-role').value});$('station-map-form').reset();await mappings();});
  ready=true;render();
}
start().catch(showError);
