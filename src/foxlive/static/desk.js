"use strict";
let snapshot=null, selected=null, detailId=null, refreshTimer=null, refreshing=false, refreshAgain=false;
const $=id=>document.getElementById(id);
const escape=value=>String(value??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
function error(message){$("error").textContent=message;$("error").hidden=!message;}
async function api(url,data,method="POST"){
 const response=await fetch(url,data===undefined?{}:{method,headers:{"Content-Type":"application/json"},body:JSON.stringify(data)});
 const value=await response.json(); if(!response.ok)throw new Error(typeof value.detail==="string"?value.detail:JSON.stringify(value.detail));return value;
}
function table(headers,rows){return `<table><thead><tr>${headers.map(h=>`<th>${escape(h)}</th>`).join("")}</tr></thead><tbody>${rows.join("")||`<tr><td colspan="${headers.length}">No records</td></tr>`}</tbody></table>`;}
const row=values=>`<tr>${values.map(v=>`<td>${v}</td>`).join("")}</tr>`;
const duration=seconds=>seconds==null?"—":`${Math.floor(seconds/3600)?Math.floor(seconds/3600)+":":""}${String(Math.floor(seconds%3600/60)).padStart(2,"0")}:${String(seconds%60).padStart(2,"0")}`;
function time(seconds){if(seconds==null)return "—";return new Date(seconds*1000).toLocaleString(undefined,{timeZone:snapshot?.event?.timezone||"UTC"});}
function field(form,name){return form.elements.namedItem(name);}
function populate(form,data){for(const[name,value]of Object.entries(data)){const element=field(form,name);if(!element)continue;
 if(element.type==="checkbox")element.checked=Boolean(value);else if(element.hasAttribute("data-instant"))element.value=localInput(value,data.timezone);else element.value=value??"";}}
function localInput(iso,zone){if(!iso)return "";const options={timeZone:zone||snapshot?.event?.timezone||"UTC",year:"numeric",month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit",second:"2-digit",hourCycle:"h23"};
 const date=new Date(iso),parts=new Intl.DateTimeFormat("sv-SE",options).format(date).replace(" ","T");
 const offset=new Intl.DateTimeFormat("en-US",{timeZone:options.timeZone,timeZoneName:"longOffset"}).formatToParts(date).find(p=>p.type==="timeZoneName").value;
 return parts+(offset==="GMT"?"Z":offset.replace("GMT",""));}
function formData(form){const data={};for(const element of form.elements){if(!element.name||element.tagName==="BUTTON")continue;
 data[element.name]=element.type==="checkbox"?element.checked:element.type==="number"?Number(element.value):element.value;}return data;}
function requireEvent(){if(!selected)throw new Error("No selected event.");return `/api/events/${selected}`;}
function schedule(){clearTimeout(refreshTimer);refreshTimer=setTimeout(refresh,60);}
async function refresh(){if(refreshing){refreshAgain=true;return;}refreshing=true;const choice=selected;
 try{const next=await api(`/api/status${choice?"?event_id="+choice:""}`);if(choice===selected){snapshot=next;selected=next.event?.id??null;render();if(detailId&&!$("detail").hidden)await showDetail(detailId);}}
 catch(e){error(e.message);}finally{refreshing=false;if(refreshAgain){refreshAgain=false;schedule();}}}
function render(){const s=snapshot,e=s.event;$("event-select").innerHTML=s.events.map(v=>`<option value="${v.id}" ${v.id===selected?"selected":""}>${escape(v.name)} — ${escape(v.state)}</option>`).join("")||"<option>No event</option>";
 $("event-title").textContent=e?.name||"Create an event to begin";$("event-description").textContent=e?.description||"";
 $("event-state").textContent=e?`${e.state} · ${e.timing_mode}${s.active_event_id&&s.active_event_id!==e.id?" · Another event is running":""}`:"No event";
 $("connection").textContent=`Source: ${s.application.serial_enabled?(s.application.source_connected===null?"connecting":s.application.source_connected?"CONNECTED":"DISCONNECTED"):"OFFLINE MODE"} ${s.application.source_port}`;
 $("sync").textContent=`TimeSync: ${!s.application.time_sync_enabled?"automatic disabled":s.diagnostics.timesync?(s.diagnostics.timesync.success?"last write OK":"FAILED"):"no recorded write"}`;
 if(s.processing_error)error(`Processing stopped: ${s.processing_error}`);
 const participants=new Map(s.participants.map(p=>[p.id,p]));const categories=new Map(s.categories.map(c=>[c.id,c]));
 const results=new Map(s.results.map(r=>[r.participant_id,r]));
 $("recent").innerHTML=table(["Local time","Station","Runner","Category","Interpretation","RSSI","Source"],s.recent.map(p=>row([
 escape(time(p.station_timestamp)),escape(p.station_name||p.station_id),p.participant_id?`<button data-detail="${p.participant_id}">#${p.start_number} ${escape(p.first_name)} ${escape(p.last_name)}</button>`:`UNKNOWN ${escape(p.uid)}`,
 escape(p.category),escape(p.status),escape(p.rssi),`#${p.id} <button data-exclude="${p.id}">Exclude</button>`])));
 $("unknown").innerHTML=table(["UID / source","Station / time","Assign to entry"],s.unknown.map(p=>row([
 `${escape(p.uid)} (#${p.id})`,`${p.station_id} · ${escape(time(p.station_timestamp))}`,
 `<select data-unknown-select="${p.id}">${s.participants.filter(v=>v.active).map(v=>`<option value="${v.id}">#${v.start_number} ${escape(v.first_name)} ${escape(v.last_name)}</option>`).join("")}</select><button data-assign="${p.id}" data-uid="${escape(p.uid)}">Assign</button>`])));
 const resultRow=r=>{const p=participants.get(r.participant_id);return row([escape(r.rank??"—"),p?.start_number,
 `<button data-detail="${p?.id}">${escape(p?.first_name)} ${escape(p?.last_name)}</button>`,r.controls,
 escape(r.status),r.status==="RUNNING"&&r.start!==null?`<span data-running-start="${r.start}">${duration(Math.max(0,Math.floor(Date.now()/1000)-r.start))}</span> (provisional)`:duration(r.elapsed),escape(time(r.start)),escape(time(r.finish))]);};
 $("rankings").innerHTML=s.categories.map(c=>{const group=s.results.filter(r=>r.category_id===c.id);return `<h4>${escape(c.code)} — ${escape(c.display_name)} ${c.active?"":"(inactive)"}</h4>
 <h5>Finished / ranked</h5>${table(["Rank","Bib","Runner","Controls","Status","Elapsed","Start","Finish"],group.filter(r=>r.rank!==null).map(resultRow))}
 <h5>Running / provisional and unranked statuses</h5>${table(["Rank","Bib","Runner","Controls","Status","Elapsed","Start","Finish"],group.filter(r=>r.rank===null).map(resultRow))}`;}).join("")||"No categories";
 $("participant-list").innerHTML=table(["Bib","Name","Category","UID","Club","State","Active","Edit"],s.participants.map(p=>row([
 p.start_number,escape(`${p.first_name} ${p.last_name}`),escape(categories.get(p.category_id)?.code),escape(p.uid),escape(p.club),escape(results.get(p.id)?.status),p.active?"Yes":"No",`<button data-edit-participant="${p.id}">Edit</button>`])));
 const categorySelect=field($("participant-form"),"category_id"), old=categorySelect.value;
 categorySelect.innerHTML=s.categories.map(c=>`<option value="${c.id}">${escape(c.code)}</option>`).join("");if(old)categorySelect.value=old;
 $("categories").innerHTML=table(["Code","Name","Active","Edit"],s.categories.map(c=>row([escape(c.code),escape(c.display_name),c.active?"Yes":"No",`<button data-edit-category="${c.id}">Edit</button>`])));
 $("station-list").innerHTML=table(["Fox ID","Name","Role","Enabled","Count","Last time","Callsign","RSSI","Edit"],s.stations.map(v=>row([
 v.station_id,escape(v.display_name),escape(v.role),v.enabled?"Yes":"No",v.punch_count||0,escape(time(v.last_time)),escape(v.callsign),escape(v.rssi),`<button data-edit-station="${v.station_id}">Edit</button>`])));
 $("export-participants").href=e?`/api/events/${e.id}/export/participants`:"#";$("export-results").href=e?`/api/events/${e.id}/export/results`:"#";
 document.querySelectorAll("[data-state]").forEach(button=>button.disabled=!e||e.state==="ARCHIVED");
 tick();
}
function tick(){if(!snapshot?.event)return;$("clock").textContent=`${snapshot.event.timezone}: ${new Date().toLocaleString(undefined,{timeZone:snapshot.event.timezone})}`;
 document.querySelectorAll("[data-running-start]").forEach(e=>e.textContent=duration(Math.max(0,Math.floor(Date.now()/1000)-Number(e.dataset.runningStart))));}
function action(callback){return async event=>{event?.preventDefault();error("");try{await callback(event);await refresh();}catch(e){error(e.message);}};}
$("event-select").onchange=event=>{selected=Number(event.target.value)||null;detailId=null;$("detail").hidden=true;refresh();};
$("event-form").onsubmit=action(async()=>{const data=formData($("event-form")),id=data.id;delete data.id;
 for(const key of["competition_start_at","competition_end_at","default_start_at"])data[key]=data[key]||null;
 if(id){const old=snapshot.events.find(e=>e.id===Number(id));data.minimum_unix_timestamp=old.minimum_unix_timestamp;data.maximum_receive_skew_seconds=old.maximum_receive_skew_seconds;}
 const saved=await api(id?`/api/events/${id}`:"/api/events",data,id?"PUT":"POST");selected=saved.id;populate($("event-form"),saved);});
$("new-event").onclick=()=>{$("event-form").reset();field($("event-form"),"id").value="";};
$("event-select").addEventListener("change",()=>{const event=snapshot?.events.find(e=>e.id===selected);if(event)populate($("event-form"),event);});
document.querySelectorAll("[data-state]").forEach(b=>b.onclick=action(()=>api(requireEvent()+"/state",{state:b.dataset.state})));
$("recalculate").onclick=action(async()=>{const counts=await api(requireEvent()+"/recalculate",{});$("import-summary").textContent="Recalculation: "+JSON.stringify(counts,null,2);});
$("category-form").onsubmit=action(async()=>{const data=formData($("category-form")),id=data.id;delete data.id;await api(requireEvent()+"/categories"+(id?"/"+id:""),data,id?"PUT":"POST");$("category-form").reset();field($("category-form"),"id").value="";});
$("participant-form").onsubmit=action(async()=>{const data=formData($("participant-form")),id=data.id;delete data.id;data.category_id=Number(data.category_id);data.uid=data.uid||null;data.start_time=data.start_time||null;data.manual_status=data.manual_status||null;
 await api(requireEvent()+"/participants"+(id?"/"+id:""),data,id?"PUT":"POST");$("participant-form").reset();field($("participant-form"),"id").value="";});
$("new-participant").onclick=()=>{$("participant-form").reset();field($("participant-form"),"id").value="";};
$("station-form").onsubmit=action(async()=>{const data=formData($("station-form"));await api(requireEvent()+"/stations/"+data.station_id,data,"PUT");});
$("import-form").onsubmit=action(async event=>{const summary=await api(requireEvent()+"/import",{text:field($("import-form"),"text").value,commit:event.submitter?.value==="commit"});$("import-summary").textContent=JSON.stringify(summary,null,2);});
$("csv-file").onchange=action(async event=>{const file=event.target.files[0];if(file&&file.size>2000000)throw new Error("CSV exceeds 2 MB");if(file)field($("import-form"),"text").value=new TextDecoder("utf-8",{fatal:true}).decode(await file.arrayBuffer());});
$("associate-form").onsubmit=action(()=>api(requireEvent()+"/associate",{punch_ids:field($("associate-form"),"punch_ids").value.split(",").map(v=>Number(v.trim()))}));
$("source-list").onclick=action(async()=>{$("source-summary").textContent=JSON.stringify(await api("/api/source-punches?limit=100"),null,2);});
$("load-audit").onclick=action(async()=>{const rows=await api(`/api/audit?event_id=${selected}`);$("audit-list").innerHTML=table(["UTC","Operator","Action","Entity","Before / after","Reason"],rows.map(r=>row([
 escape(r.created_at),escape(r.operator),escape(r.action),escape(r.entity),escape(JSON.stringify({before:r.before,after:r.after})),escape(r.reason)])));});
document.body.addEventListener("click",event=>{const b=event.target.closest("button");if(!b||!["editParticipant","editCategory","editStation","assign","exclude","detail"].some(key=>b.dataset[key]))return;
 action(async()=>{
 if(b.dataset.editParticipant){populate($("participant-form"),snapshot.participants.find(p=>p.id===Number(b.dataset.editParticipant)));$("participant-form").scrollIntoView();}
 if(b.dataset.editCategory)populate($("category-form"),snapshot.categories.find(c=>c.id===Number(b.dataset.editCategory)));
 if(b.dataset.editStation)populate($("station-form"),snapshot.stations.find(s=>s.station_id===Number(b.dataset.editStation)));
 if(b.dataset.assign){const participant=Number(document.querySelector(`[data-unknown-select="${b.dataset.assign}"]`).value);const data={...snapshot.participants.find(p=>p.id===participant)};
  for(const key of["id","event_id","created_at","updated_at"])delete data[key];data.uid=b.dataset.uid;
  if(confirm(`Assign UID ${data.uid} to #${data.start_number}? Existing UID mapping/history will be reinterpreted and audited.`))await api(requireEvent()+"/participants/"+participant,data,"PUT");}
 if(b.dataset.exclude){const reason=prompt("Reason to exclude this source interpretation (source stays unchanged):");if(reason)await api(requireEvent()+"/punches/"+b.dataset.exclude+"/exclude",{reason});}
 if(b.dataset.detail){detailId=Number(b.dataset.detail);$("detail").hidden=false;await showDetail(detailId);$("detail").scrollIntoView();}
 })(event);
});
async function showDetail(id){const event=selected,data=await api(requireEvent()+"/participants/"+id),p=data.participant,r=data.result;
 if(event!==selected||detailId!==id)return;
  const category=snapshot.categories.find(c=>c.id===p.category_id);
  $("detail").hidden=false;$("detail-body").innerHTML=`<p>#${p.start_number} ${escape(p.first_name)} ${escape(p.last_name)} · ${escape(p.club)} · category ${escape(category?.code)} · UID ${escape(p.uid)} · ${escape(r.status)} · controls ${r.controls}</p>
  <p>Start ${escape(time(r.start))} · finish ${escape(time(r.finish))} · elapsed ${duration(r.elapsed)}</p>`+table(["Time","Station","Interpretation","Reason","RSSI","Source"],data.history.map(v=>row([
  escape(time(v.station_timestamp)),escape(v.station_name||v.station_id),escape(v.status),escape(v.reason),escape(v.rssi),`#${v.id} / raw #${v.raw_event_id}`])));
}
$("close-detail").onclick=()=>{detailId=null;$("detail").hidden=true;};
function connect(){const ws=new WebSocket(`${location.protocol==="https:"?"wss":"ws"}://${location.host}/ws`);
 ws.onopen=()=>{$("socket").textContent="Updates: LIVE";schedule();};ws.onmessage=()=>schedule();
 ws.onerror=()=>ws.close();ws.onclose=()=>{$("socket").textContent="Updates: reconnecting";setTimeout(connect,2000);};}
$("event-form").elements.namedItem("date").value=new Date().toISOString().slice(0,10);
setInterval(tick,1000);refresh().then(()=>{if(snapshot?.event)populate($("event-form"),snapshot.event);});connect();
