"use strict";
/* Presentation/actions only: reconciliation and scoring stay on the owner-loop service. */
window.FoxLiveEvidence = (() => {
  let currentReview=null, chosen=null, imported=null;
  const label=value=>t('evidence.'+value);
  const person=id=>snapshot.participants.find(p=>p.id===id);
  const personLabel=id=>{const p=person(id);return p?`#${p.start_number} ${p.first_name} ${p.last_name}`:t('rfid.unknown');};
  const station=id=>{const s=snapshot.stations.find(s=>s.station_id===id);return (s?.display_name || (id===-1?t('readout.session'):t('station.fallback',{number:id})))+(s?.role==='BEACON'?' · '+t('station.BEACON'):'');};
  const options=(rows,value,label)=>rows.map(r=>`<option value="${value(r)}">${escape(label(r))}</option>`).join('');
  const names=r=>`${personLabel(r.participant_id)} · ${station(r.station_id)}`;
  function render() {
    if(!snapshot) return;
    const stats=snapshot.reconciliation;
    $('readout-stats').textContent=t('readout.statistics',{readouts:stats.readouts||0,recovered:stats.recovered||0,reviews:stats.open_reviews||0,manual:stats.manual_decisions||0});
    $('evidence-overview').textContent=$('readout-stats').textContent;
    $('export-evidence').href=selected?requireEvent()+'/export/evidence':'#';
    $('readout-list').innerHTML=table(['time.local','participant.label','rfid.label','readout.status','common.details'],snapshot.readouts.map(r=>row([escape(time(r.received_at)),escape(personLabel(r.participant_id)),escape(r.uid),escape(t('readout.'+r.status)),`<button data-readout="${r.id}">${escape(t('common.details'))}</button>`])));
    $('review-list').innerHTML=snapshot.reviews.length?table(['participant.label','station.label','review.issue','common.actions'],snapshot.reviews.map(r=>row([escape(personLabel(r.participant_id)),escape(station(r.station_id)),escape(r.resolution.issues.map(label).join(' · ')),r.participant_id?`<button data-review="${r.id}">${escape(t('review.open'))}</button>`:`<button data-unknown-readout="${escape(r.uid)}">${escape(t('rfid.assign_or_register'))}</button>`]))):`<p>${escape(t('review.empty'))}</p>`;
    const select=$('readout-participant'),old=select.value;
    select.innerHTML=`<option value="">${escape(t('rfid.choose_participant'))}</option>`+options(snapshot.participants.filter(p=>p.active),p=>p.id,p=>personLabel(p.id));select.value=old;
    // Retain operator timestamps/checks while live updates arrive.
    const records=$('readout-records'),stations=JSON.stringify(snapshot.stations.map(s=>[s.station_id,s.display_name,s.role,s.enabled]));if(records.dataset.event!==String(selected)||records.dataset.stations!==stations){
      records.dataset.event=String(selected);records.dataset.stations=stations;
      records.innerHTML=snapshot.stations.filter(s=>s.enabled&&s.station_id<=255).map(s=>`<label><span><input type="checkbox" data-read-file="${s.station_id}"> ${escape(station(s.station_id))}</span><input type="datetime-local" step="1" data-record-time="${s.station_id}" value="${UI.localInput(new Date().toISOString(),zone())}"><select data-record-fold="${s.station_id}" hidden></select></label>`).join('');
    }
    if(imported && imported.event_id===selected) { const latest=snapshot.readouts.find(r=>r.id===imported.id); if(latest) imported={...imported,...latest}; renderImported(imported); }
    if($('review-dialog').open)reviewAction();
    // The embedded event ID is advanced configuration, not a database primary key.
  }
  function renderImported(data) {
    const p=person(data.participant_id), summary=data.summary||{};
    $('readout-result').innerHTML=`<h3>${escape(p?personLabel(p.id):t('rfid.unknown'))}</h3><p>${escape(t('readout.'+data.status))} · ${escape(t('readout.record_count',{count:data.records.length,failed:data.records.filter(r=>r.parse_status==='MALFORMED').length}))}</p><p>${escape(t('readout.summary',{live:summary.live_controls||0,tag:summary.tag_controls||0,recovered:summary.recovered||0,matches:summary.matches||0,reviews:summary.open_reviews||0}))}</p><p>${escape(t('readout.completion',{controls:summary.controls_found||0,beacon:t(summary.beacon_punched?'beacon.present':'beacon.missing'),finish:t(summary.finish_punched?'beacon.present':'beacon.missing')}))}</p><p>${escape(t(summary.open_reviews||data.status!=='COMPLETE'||!p?'evidence.REVIEW_REQUIRED':'evidence.COMPLETE'))}</p>`+(p?`<button data-detail="${p.id}">${escape(t('participant.detail'))}</button>`:data.uid?`<p>${escape(data.uid)}</p><button data-unknown-readout="${escape(data.uid)}">${escape(t('rfid.assign_or_register'))}</button>`:'');
    if(data.status!=='COMPLETE') $('readout-result').insertAdjacentHTML('beforeend',`<p>${escape(t('readout.retry'))}</p>`);
  }
  function detail(data) {
    const result=data.result;
    return `<h3>${escape(t('review.evidence'))}</h3><p>${escape(label(result.completeness))} · ${escape(label(result.provenance))}</p>`+table(['station.label','review.outcome','review.evidence','common.actions'],data.evidence.map(r=>row([escape(station(r.station_id)),escape(t(r.role==='BEACON'&&r.status==='TAG_ONLY_RECOVERED'?'beacon.recovered':'evidence.'+r.status))+(r.needs_review?' · '+escape(label('REVIEW_REQUIRED')):'')+'<br>'+r.scored.map(s=>escape(t('punch.'+s.status))).join(' · ')+(r.presence_only?'<br>'+escape(label(r.role==='BEACON'?'BEACON_PRESENCE':'PRESENCE')):''),r.evidence.map(e=>`${escape(label(e.source_type))} ${escape(time(e.station_timestamp))} · ${escape(label(e.validity))}`).join('<br>'),`<button data-review-station="${r.station_id}" data-entry="${data.participant.id}">${escape(t('review.open'))}</button>`])))+`<button data-manual-entry="${data.participant.id}">${escape(t('review.add_manual'))}</button>`+table(['time.local','history.operator','review.action','history.reason'],data.decisions.map(d=>row([escape(time(d.created_at)),escape(d.operator),escape(t(d.action==='PRESENCE'&&snapshot.stations.find(s=>s.station_id===d.station_id)?.role==='BEACON'?'review.beacon_presence':'review.'+d.action)),escape(d.reason)])));
  }
  async function openReview(resolution=null, entry=null) {
    currentReview=resolution;chosen=null;const form=$('review-form');form.reset();
    const participant=field(form,'participant_id');participant.innerHTML=options(snapshot.participants.filter(p=>p.active),p=>p.id,p=>personLabel(p.id));participant.value=String(resolution?.participant_id||entry||participant.value);
    const choices=snapshot.stations.filter(s=>s.enabled);if(resolution&&!choices.some(s=>s.station_id===resolution.station_id))choices.unshift({station_id:resolution.station_id,display_name:station(resolution.station_id)});
    field(form,'station_id').innerHTML=options(choices,s=>s.station_id,s=>station(s.station_id));if(resolution)field(form,'station_id').value=String(resolution.station_id);
    field(form,'action').value=resolution?'SELECT':'MANUAL';
    $('review-evidence').innerHTML=resolution?`<h3>${escape(names(resolution))}</h3><p>${escape(resolution.issues.map(label).join(' · '))}</p>`+table(['review.evidence','time.local','review.issue','common.actions'],resolution.evidence.map((e,index)=>row([escape(label(e.source_type)),escape(time(e.station_timestamp)),escape(label(e.validity))+(e.tag_event_id!=null?'<br>'+escape(t('readout.event_comparison',{stored:e.tag_event_id,current:snapshot.event.tag_event_id??'—'})):''),e.validity==='VALID'&&e.source_type!=='MANUAL'?`<button type="button" data-select-evidence="${index}">${escape(t('review.use_evidence'))}</button>`:'']))):'';
    field(form,'timestamp').value=UI.localInput(new Date().toISOString(),zone());resetChoice(field(form,'timestamp'));reviewAction();
    $('detail').close();$('review-dialog').showModal();
  }
  function reviewAction() {
    const form=$('review-form'),action=field(form,'action'),role=snapshot.stations.find(s=>s.station_id===Number(field(form,'station_id').value))?.role;
    const isStatus=['DNS','DNF','DSQ','STATUS_AUTO'].includes(action.value);field(form,'station_id').parentElement.hidden=isStatus;field(form,'station_id').required=!isStatus;
    for(const option of action.options)option.disabled=(option.value==='PRESENCE'&&!['CONTROL','BEACON'].includes(role))||(['SELECT','MANUAL'].includes(option.value)&&!role);
    const presence=action.querySelector('[value="PRESENCE"]');presence.removeAttribute('data-i18n');presence.textContent=t(role==='BEACON'?'review.beacon_presence':'review.PRESENCE');
    if(action.selectedOptions[0]?.disabled)action.value='EXCLUDE';
    field(form,'timestamp').parentElement.hidden=action.value!=='MANUAL';
    field(form,'timestamp').required=action.value==='MANUAL';
  }
  field($('review-form'),'action').onchange=reviewAction;
  field($('review-form'),'station_id').onchange=()=>{currentReview=null;chosen=null;field($('review-form'),'action').value='MANUAL';$('review-evidence').replaceChildren();reviewAction();};
  field($('review-form'),'participant_id').onchange=()=>{currentReview=null;chosen=null;field($('review-form'),'action').value='MANUAL';$('review-evidence').replaceChildren();reviewAction();};
  $('close-review').onclick=()=>$('review-dialog').close();
  $('add-manual-evidence').onclick=action(()=>openReview());
  $('review-form').onsubmit=action(async()=>{
    const form=$('review-form'),data=formData(form);data.participant_id=Number(data.participant_id);data.station_id=Number(data.station_id);
    if(data.action==='SELECT'&&!chosen)throw problem('review.choose_evidence');
    if(chosen&&data.action==='SELECT'){data.source_type=chosen.source_type;data.source_id=chosen.source_id;}
    if(data.action==='MANUAL')await dates(form,data,zone());else data.timestamp=null;
    if(!confirm(t('review.confirm_decision')))return;
    if(['DNS','DNF','DSQ','STATUS_AUTO'].includes(data.action)){await api(requireEvent()+'/participants/'+data.participant_id+'/status',{status:data.action==='STATUS_AUTO'?null:data.action,reason:data.reason,operator:data.operator});$('review-dialog').close();return;}
    await api(requireEvent()+'/decisions',data);$('review-dialog').close();
  });
  $('readout-participant').onchange=event=>{field($('readout-simulate'),'uid').value=person(Number(event.target.value))?.uid||'';};
  $('readout-simulate').onsubmit=action(async()=>{
    const data=formData($('readout-simulate'));data.records=[];
    for(const check of $('readout-records').querySelectorAll('[data-read-file]:checked')){
      const input=$('readout-records').querySelector(`[data-record-time="${check.dataset.readFile}"]`),fold=$('readout-records').querySelector(`[data-record-fold="${check.dataset.readFile}"]`);
      const choices=(await api('/api/ui/local-time',{value:input.value,timezone:zone()})).options;
      if(choices.length>1){const signature=input.value+'|'+zone();if(fold.dataset.signature!==signature){fold.innerHTML='<option value="">'+escape(t('time.choose_occurrence'))+'</option>'+choices.map((c,i)=>`<option value="${c.instant}">${escape(t(i?'time.second':'time.first',{offset:c.offset}))}</option>`).join('');fold.dataset.signature=signature;}fold.hidden=false;if(!fold.value)throw problem('time.ambiguous');}
      data.records.push({file_id:Number(check.dataset.readFile),timestamp:choices.length===1?choices[0].instant:fold.value});
    }
    imported=await api(requireEvent()+'/readouts/simulate',data);renderImported(imported);
  });
  $('readout-file').onchange=action(async event=>{const file=event.target.files[0];if(!file)return;if(file.size>1048576)throw problem('readout.too_large');const bytes=new Uint8Array(await file.arrayBuffer());let binary='';for(let offset=0;offset<bytes.length;offset+=32768)binary+=String.fromCharCode(...bytes.subarray(offset,offset+32768));imported=await api(requireEvent()+'/readouts/import',{raw_base64:btoa(binary)});renderImported(imported);event.target.value='';});
  $('load-review-history').onclick=action(async()=>{const rows=await api(requireEvent()+'/reviews?include_resolved=true');$('review-history').innerHTML=table(['participant.label','station.label','review.outcome','common.actions'],rows.map(r=>row([escape(personLabel(r.participant_id)),escape(station(r.station_id)),escape(t('review.'+r.status)),r.participant_id?`<button data-history-review="${r.id}">${escape(t('review.open'))}</button>`:''])));});
  document.addEventListener('click',event=>{const button=event.target.closest('button');if(!button||!['selectEvidence','readout','review','historyReview','reviewStation','manualEntry','unknownReadout'].some(key=>key in button.dataset))return;action(async()=>{
    if(button.dataset.selectEvidence){chosen=currentReview.evidence[Number(button.dataset.selectEvidence)];field($('review-form'),'action').value='SELECT';reviewAction();button.textContent=t('review.selected');}
    if(button.dataset.readout){imported=await api(requireEvent()+'/readouts/'+button.dataset.readout);renderImported(imported);}
    if(button.dataset.review){await openReview(snapshot.reviews.find(r=>r.id===Number(button.dataset.review)).resolution);}
    if(button.dataset.historyReview){const rows=await api(requireEvent()+'/reviews?include_resolved=true');await openReview(rows.find(r=>r.id===Number(button.dataset.historyReview)).resolution);}
    if(button.dataset.reviewStation){const data=await api(requireEvent()+'/evidence?participant_id='+button.dataset.entry);await openReview(data.resolutions.find(r=>r.station_id===Number(button.dataset.reviewStation)));}
    if(button.dataset.manualEntry)await openReview(null,Number(button.dataset.manualEntry));
    if(button.dataset.unknownReadout){
      // The import response is authoritative before its WebSocket refresh arrives.
      // Do not make immediate registration depend on the recent-snapshot cache.
      let session=imported?.event_id===selected&&imported.uid===button.dataset.unknownReadout?imported:snapshot.readouts.find(r=>r.uid===button.dataset.unknownReadout);
      if(!session) return;session=await api(requireEvent()+'/readouts/'+session.id);const record=session.records.find(r=>r.station_timestamp!=null);newRegistration();capture.choose({uid:session.uid,readout_id:session.id,received_at:session.received_at,station_name:record?station(record.file_id):t('readout.session'),station_id:record?.file_id,station_timestamp:record?.station_timestamp,station_time_valid:Boolean(record?.synchronized)},context());tagView();$('unknown-entry-panel').hidden=false;
    }
  })(event);});
  // Advanced event setting uses the existing form/save path.
  const labelNode=document.createElement('label');labelNode.textContent='';const span=document.createElement('span');span.dataset.i18n='readout.event_id';span.textContent='';const input=document.createElement('input');input.name='tag_event_id';input.type='number';input.min='0';input.max='65535';labelNode.append(span,input);$('event-form').querySelector('details').append(labelNode);
  for(const value of ['DNS','DNF','DSQ','STATUS_AUTO']){const option=document.createElement('option');option.value=value;option.dataset.i18n=value==='STATUS_AUTO'?'review.STATUS_AUTO':'participant.'+value;field($('review-form'),'action').append(option);}
  const overview=document.createElement('p');overview.id='evidence-overview';$('administration').append(overview);
  return {render,detail};
})();
