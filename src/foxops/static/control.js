"use strict";
const UI=globalThis.FoxLiveUI, $=id=>document.getElementById(id);
let state, catalogs, t, busy=false, exiting=false, language=UI.preferred(localStorage);
async function api(path,body) {
  const response=await fetch('/api/ops/'+path,{headers:{'Accept-Language':language,...(body!==undefined?{'Content-Type':'application/json'}:{})},...(body!==undefined?{method:'POST',body:JSON.stringify(body)}:{})});
  const result=await response.json();if(!response.ok)throw new Error(typeof result.detail==='string'?result.detail:t('invalid'));return result;
}
function stamp(value){return value?new Date(value).toLocaleString(language==='de'?'de-DE':'en-GB'):'—';}
function render(){
  t=UI.translator(catalogs,language);document.documentElement.lang=language;$('language').value=language;
  document.querySelectorAll('[data-t]').forEach(node=>node.textContent=t(node.dataset.t));
  if(!state)return;
  $('source-state').textContent=t('state.'+state.source.state);$('source-port').textContent=state.source.port||'—';
  const sync=state.source.timesync;
  $('source-sync').textContent=!state.source.time_sync_enabled?t('sync_disabled'):sync?t(sync.success?'sync_written':'sync_failed')+' · '+stamp(sync.recorded_at):t('sync_pending');
  $('source-message').textContent=stamp(state.source.last_message);$('source-error').textContent=state.source.last_error||'—';$('identity').hidden=!state.identity_confirmation;
  $('core-state').textContent=t('state.'+state.core.state);$('core-counts').textContent=t('core_counts',{raw:state.core.statistics.raw_events,punches:state.core.statistics.punches});
  $('live-state').textContent=t('state.'+state.live.state);$('live-event').textContent=state.live.event?state.live.event.name:t('no_event');$('live-error').textContent=state.live.last_error||'';
  $('bridge-state').textContent=t('state.'+state.bridge.state);$('bridge-output').textContent=state.bridge.configured?state.bridge.endpoint:'—';
  $('bridge-error').textContent=state.bridge.last_error||'—';$('bridge-toggle').textContent=t(state.bridge.running?'stop_bridge':'start_bridge');
  const last=state.bridge.last_delivery,counts=state.bridge.status_counts;
  $('bridge-delivery').textContent=t('delivery_counts',{sent:counts.sent||0,failed:(counts.failed||0)+(counts.uncertain||0)+(counts.mapping_error||0)+(counts.encoding_error||0),queued:state.bridge.queue_size})+(last?' · '+last.status+(last.error?' · '+last.error:''):'');
  $('system-data').textContent=state.system.database;$('system-version').textContent=state.version;$('system-logs').textContent=state.system.logs;$('system-settings').textContent=state.system.settings;$('system-process').textContent=t('process_detail',{pid:state.pid});
  document.querySelectorAll('button').forEach(node=>node.disabled=busy||exiting||state.system.restarting);
  $('bridge-toggle').disabled=busy||exiting||state.system.restarting||!state.bridge.configured;
  $('reconnect').disabled=busy||exiting||state.system.restarting||state.identity_confirmation;
  if(state.system.restarting&&!exiting)$('message').textContent=t('restarting');
}
function showError(error){$('error').textContent=error.message||String(error);$('error').hidden=false;}
function action(callback){return async()=>{if(busy)return;busy=true;render();$('error').hidden=true;try{await callback();if(!exiting)state=await api('status');render();}catch(error){showError(error);}finally{busy=false;render();}};}
async function refresh(){
  try{const previous=state;state=await api('status');if(previous?.system.restarting&&!state.system.restarting)$('message').textContent=t('runtime_ready');$('error').hidden=true;render();}
  catch(error){if(exiting){$('message').textContent=t('stopped');return;}if(!state?.system.restarting)showError(error);}
  setTimeout(refresh,1000);
}
async function start(){
  catalogs=Object.fromEntries(await Promise.all(['en','de'].map(async lang=>[lang,await(await fetch('/ops/static/'+lang+'.json')).json()])));
  t=UI.translator(catalogs,language);state=await api('status');if(!localStorage.getItem('foxlive.language'))language=state.system.language;render();
  $('language').onchange=()=>{language=$('language').value;UI.remember(localStorage,language);render();};
  $('reconnect').onclick=action(()=>api('reconnect',{}));
  $('bridge-toggle').onclick=action(()=>api('bridge/state',{running:!state.bridge.running}));
  $('diagnostics').onclick=action(async()=>{const entries=await api('diagnostics');$('diagnostic-entries').textContent=entries.map(item=>stamp(item.created_at)+' · '+item.kind+'\n'+item.detail).join('\n\n');$('diagnostic-panel').open=true;});
  $('restart').onclick=action(async()=>{await api('restart',{});$('message').textContent=t('restarting');});
  $('exit').onclick=action(async()=>{if(!confirm(t('confirm_shutdown')))return;await api('shutdown',{});exiting=true;$('message').textContent=t('stopping');});
  setTimeout(refresh,1000);
}
start().catch(showError);
