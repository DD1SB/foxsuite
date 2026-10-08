"use strict";
const UI = FoxLiveUI, $ = id => document.getElementById(id);
const preferences = (() => { try { return localStorage; } catch { return {getItem:() => null,setItem:() => {}}; } })();
// Do not accept actions before the local catalogs/snapshot have initialized.
const startupControls = [...document.querySelectorAll("input,select,textarea,button")];
startupControls.forEach(control => control.disabled = true);
let catalogs, lang = "en", t, snapshot = null, selected = null, detailId = null;
let refreshTimer, refreshing = false, refreshAgain = false, socketConnected = false;
let recentTags = [], auditRows = null, sourceRows = null, importSummary = null, lastError = null;
let masterAuditRows = null;
let captureGeneration = 0, captureStarted = 0, polling = false, tagNotice = null;
let masters = {runners:[],clubs:[],categories:[]}, mastersDirty = true, newPerson = false;
let workspace, combos = {}, summary = {runners:[],clubs:[],categories:[]}, stagedClub = null, clubTarget = null, enablingCategory = null;
let runnerReviewed = '', pendingRunnerMatches = [], clubReviewed = false, pageNumbers = {}, tablePageSize = 50;
const capture = new UI.TagCapture();
const escape = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const field = (form, name) => form.elements.namedItem(name);
const zone = () => snapshot?.event?.timezone || "UTC";
const time = value => UI.dateTime(value, zone(), lang);
const localDate = value => value ? new Intl.DateTimeFormat(UI.locale(lang), {timeZone:'UTC',dateStyle:'medium'}).format(new Date(value+'T12:00Z')) : '—';
const duration = seconds => seconds == null ? "—" : `${Math.floor(seconds/3600) ? Math.floor(seconds/3600)+":" : ""}${String(Math.floor(seconds%3600/60)).padStart(2,"0")}:${String(seconds%60).padStart(2,"0")}`;
const row = values => `<tr>${values.map(v => `<td>${v ?? "—"}</td>`).join("")}</tr>`;
function table(keys, rows) {
  return `<table><thead><tr>${keys.map(k => `<th>${escape(t(k))}</th>`).join("")}</tr></thead><tbody>${rows.join("") || `<tr><td colspan="${keys.length}">${escape(t("common.empty"))}</td></tr>`}</tbody></table>`;
}
function problem(key, values = {}) { const e = new Error(); e.key = key; e.values = values; return e; }
const fieldKeys = {name:"common.name", date:"event.date", timezone:"event.timezone", timing_mode:"event.timing", competition_start_at:"event.window_start", competition_end_at:"event.window_end", default_start_at:"event.default_start", code:"category.code", display_name:"common.name", display_name_en:"category.name_en", display_name_de:"category.name_de", birth_year:"runner.birth_year", birth_date:"runner.birth_date", runner_id:"runner.choose", club_id:"participant.club", checked_in:"registration.checked_in", start_number:"participant.start_number", first_name:"participant.first_name", last_name:"participant.last_name", category_id:"category.label", uid:"rfid.label", club:"participant.club", start_time:"participant.predefined_start", manual_status:"participant.status", station_id:"station.number", role:"station.role", reason:"history.reason", text:"csv.text"};
function message(detail) {
  if (typeof detail === "string") return detail;
  return (detail || []).map(e => `${t(fieldKeys[e.loc?.at(-1)] || "common.details")}: ${e.msg}`).join(" · ");
}
function error(value) {
  lastError = value;
  $("error").textContent = value ? value.key ? t(value.key, value.values) : message(value.uiDetail?.[lang] || value.message) : "";
  $("error").hidden = !value;
  document.querySelectorAll('dialog[open] .dialog-error').forEach(node => {node.textContent=$("error").textContent; node.hidden=!value;});
  if ($("registration-dialog").open) { $("registration-error").textContent = $("error").textContent; $("registration-error").hidden = !value; }
  document.querySelectorAll('.local-error').forEach(e => e.remove());
  if (value) {
    const details = value.uiDetail?.[lang];
    const form = document.activeElement?.closest('form') || ($("registration-dialog").open ? $("participant-form") : null);
    if (form && Array.isArray(details)) details.forEach(e => {
      const input=field(form,e.loc?.at(-1)) || form.querySelector(`[data-person="${e.loc?.at(-1)}"]`);
      if (input) { const notice=document.createElement('p'); notice.className='local-error'; notice.textContent=e.msg; input.parentElement.append(notice); }
    });
  }
}
async function api(url, data, method = "POST") {
  let response;
  try { response = await fetch(url, {headers:{"Accept-Language":lang, ...(data === undefined ? {} : {"Content-Type":"application/json"})}, ...(data === undefined ? {} : {method,body:JSON.stringify(data)})}); }
  catch { throw problem("error.network"); }
  const value = await response.json();
  if (!response.ok) { const e = new Error(message(value.detail)); e.uiDetail = value.ui_detail; throw e; }
  return value;
}
function requireEvent() { if (!selected) throw problem("error.select_event"); return `/api/events/${selected}`; }
function action(callback) { return async event => {
  event?.preventDefault(); const form = event?.target?.tagName === "FORM" ? event.target : null;
  if (form?.dataset.saving) return;
  if (form) form.dataset.saving = "true";
  error(null); try { await callback(event); await refresh(); } catch (e) { error(e); }
  finally { if (form) delete form.dataset.saving; }
}; }
function nativeMessage(input) {
  const v = input.validity;
  if (v.valueMissing) return t("error.required");
  if (v.rangeUnderflow) return t("error.minimum", {count:input.min});
  if (v.rangeOverflow) return t("error.maximum", {count:input.max});
  if (v.badInput || v.stepMismatch) return t("error.number");
  if (v.tooLong) return t("error.too_long", {count:input.maxLength});
  return t("error.validation");
}
document.addEventListener("invalid", event => { event.target.setCustomValidity(nativeMessage(event.target)); }, true);
document.addEventListener("input", event => { if (event.target.setCustomValidity) event.target.setCustomValidity(""); });
document.addEventListener("change", event => { if (event.target.setCustomValidity) event.target.setCustomValidity(""); });
function populate(form, data) {
  form.dataset.entityId = data.id ?? "";
  if (form.id === "participant-form" && data.runner_id) {
    const runner = masters.runners.find(r => r.id === data.runner_id) || data;
    combos.runner?.set(runner);
  }
  for (const [name,value] of Object.entries(data)) {
    const input = field(form, name); if (!input) continue;
    input.setCustomValidity("");
    if (input.type === "checkbox") input.checked = Boolean(value);
    else if (input.hasAttribute("data-instant")) {
      const tz = data.timezone || zone(); input.value = UI.localInput(value, tz);
      input.dataset.originalInstant = value || ""; input.dataset.originalValue = input.value; input.dataset.originalZone = tz;
      resetChoice(input);
    } else input.value = value ?? "";
    if (input.type === 'hidden' && input.closest('[data-combo]')) {
      const key=input.closest('[data-combo]').dataset.combo;
      const rows=key.includes('club')?masters.clubs:key==='runner'?masters.runners:[...(snapshot?.categories||[]),...masters.categories];
      combos[key]?.set(rows.find(r => r.id===Number(value)));
    }
  }
  timeCaptions(); tagView();
}
function resetForm(form) {
  form.reset(); form.dataset.entityId = "";
  form.querySelectorAll("input").forEach(input => input.setCustomValidity(""));
  form.querySelectorAll("[data-instant]").forEach(input => { delete input.dataset.originalInstant; delete input.dataset.originalValue; delete input.dataset.originalZone; resetChoice(input); });
  form.querySelectorAll('[data-combo]').forEach(root => combos[root.dataset.combo]?.set(null));
}
function resetChoice(input) {
  const choice = input.parentElement.querySelector("[data-time-choice]");
  choice.hidden = true; choice.replaceChildren(); delete choice.dataset.signature;
}
function formData(form) {
  const data = {};
  for (const input of form.elements) {
    if (!input.name || input.tagName === "BUTTON") continue;
    data[input.name] = input.type === "checkbox" ? input.checked : input.type === "number" ? Number(input.value) : input.value;
  }
  return data;
}
async function dates(form, data, tz) {
  for (const input of form.querySelectorAll("[data-instant]")) {
    if (!input.value) { data[input.name] = null; continue; }
    if (input.value === input.dataset.originalValue && tz === input.dataset.originalZone && input.dataset.originalInstant) {
      data[input.name] = input.dataset.originalInstant; continue;
    }
    const choice = input.parentElement.querySelector("[data-time-choice]");
    const signature = `${input.value}|${tz}`;
    const result = await api("/api/ui/local-time", {value:input.value,timezone:tz});
    if (result.options.length === 1) { data[input.name] = result.options[0].instant; resetChoice(input); continue; }
    if (choice.dataset.signature !== signature) {
      choice.innerHTML = `<option value="">${escape(t("time.choose_occurrence"))}</option>` + result.options.map((o,i) => `<option value="${o.instant}" data-occurrence="${i}" data-offset="${o.offset}">${escape(t(i === 0 ? "time.first" : "time.second", {offset:o.offset}))}</option>`).join("");
      choice.dataset.signature = signature;
    }
    choice.hidden = false;
    if (!choice.value) { choice.focus(); throw problem("time.ambiguous"); }
    data[input.name] = choice.value;
  }
}
function timeCaptions() {
  document.querySelectorAll("[data-instant]").forEach(input => {
    const caption = input.parentElement.querySelector("[data-time-caption]");
    // A caption is localized explicitly; native picker chrome follows the browser/OS.
    caption.textContent = input.value ? UI.dateTime(input.value+"Z","UTC",lang) : "";
    const choice = input.parentElement.querySelector("[data-time-choice]");
    for (const option of choice.options) option.textContent = option.value ? t(option.dataset.occurrence === "0" ? "time.first" : "time.second", {offset:option.dataset.offset}) : t("time.choose_occurrence");
  });
  const date = field($("event-form"), "date");
  date.parentElement.querySelector("output").textContent = date.value ? new Intl.DateTimeFormat(UI.locale(lang), {timeZone:"UTC",year:"numeric",month:"2-digit",day:"2-digit"}).format(new Date(date.value + "T12:00:00Z")) : "";
}
document.querySelectorAll("[data-instant]").forEach(input => input.addEventListener("input", () => { resetChoice(input); timeCaptions(); }));
field($("event-form"),"date").addEventListener("input", timeCaptions);
function schedule() { clearTimeout(refreshTimer); refreshTimer = setTimeout(refresh, 60); }
async function refresh() {
  if (refreshing) { refreshAgain = true; return; } refreshing = true; const choice = selected;
  try {
    const next = await api(`/api/status${choice ? "?event_id=" + choice : ""}`);
    if (choice === selected) {
      if (mastersDirty) { await loadMasters(); mastersDirty = false; }
      if (choice !== selected) return;
      snapshot = next; selected = next.event?.id ?? null; render();
      if (detailId && $("detail").open) await showDetail(detailId);
      await loadTags();
    }
  } catch (e) { error(e); } finally { refreshing = false; if (refreshAgain) { refreshAgain = false; schedule(); } }
}
const stationName = p => p.station_name || t("station.fallback", {number:p.station_id});
const status = (prefix,value) => t(prefix + "." + (value || "PENDING_INTERPRETATION"));
const technical = value => `<details><summary>${escape(t("debug.details"))}</summary><pre>${escape(JSON.stringify(value,null,2))}</pre></details>`;
const categoryLabel = c => UI.categoryLabel(c,lang);
const runnerLabel = r => `${r.first_name} ${r.last_name} · ${r.birth_year || t("runner.birth_unknown")}${r.club || r.club_code ? " · " + [r.club_code,r.club].filter(Boolean).join(" – ") : ""}`;
function renderRunners(rows = masters.runners) {
  combos.runner?.update();
}
async function loadMasters() {
  const [runners,clubs,categories,counts] = await Promise.all([api("/api/runners?limit=10000"),api("/api/clubs"),api("/api/master/categories"),api('/api/ui/master-summary')]);
  masters = {runners,clubs,categories};
  summary=counts;
}
function pageRows(name,rows,container) {
  const page=Math.min(pageNumbers[name]||0,Math.max(0,Math.ceil(rows.length/tablePageSize)-1)); pageNumbers[name]=page;
  $(container).innerHTML=`<button data-page="${name}" data-delta="-1" ${page===0?'disabled':''}>${escape(t('common.previous'))}</button><span class="pagination-summary">${escape(t('common.page_count',{page:page+1,pages:Math.max(1,Math.ceil(rows.length/tablePageSize)),count:rows.length}))}</span><button data-page="${name}" data-delta="1" ${(page+1)*tablePageSize>=rows.length?'disabled':''}>${escape(t('common.next'))}</button>`;
  return rows.slice(page*tablePageSize,(page+1)*tablePageSize);
}
const directoryRows = key => { const words=FoxLiveCombo.tokens(document.querySelector(`[data-directory-search="${key}"]`).value); return masters[key].filter(r => words.every(w => (key==='runners'?runnerLabel(r):key==='clubs'?clubLabel(r):`${r.code} ${r.display_name_en} ${r.display_name_de}`).toLocaleLowerCase().includes(w))); };
const clubLabel = c => [c.code,c.display_name].filter((v,i,a) => v && (i===0 || v!==a[0])).join(' – ');
function renderMasters() {
  Object.values(combos).forEach(combo => combo.update());
  const counts=key => new Map(summary[key].map(r => [r.id,r])); const runners=counts('runners'), clubs=counts('clubs'), categories=counts('categories');
  $("runner-list").innerHTML = table(["common.name","runner.birth_year","participant.club","master.participations","master.last_participation","common.active","common.actions"],pageRows('runners',directoryRows('runners'),'runners-pages').map(r => row([escape(`${r.first_name} ${r.last_name}`),r.birth_year || escape(t("runner.birth_unknown")),escape([r.club_code,r.club].filter(Boolean).join(" – ")),runners.get(r.id)?.count||0,escape(localDate(runners.get(r.id)?.last_date)),t(r.active ? "common.yes" : "common.no"),`<button data-master-runner="${r.id}">${escape(t("common.edit"))}</button><button data-runner-history="${r.id}">${escape(t('master.history_runner'))}</button>`])));
  $("club-list").innerHTML = table(["club.code","common.name","runner.heading","common.active","common.actions"],pageRows('clubs',directoryRows('clubs'),'clubs-pages').map(c => row([escape(c.code),escape(c.display_name),clubs.get(c.id)?.count||0,t(c.active ? "common.yes" : "common.no"),`<button data-master-club="${c.id}">${escape(t("common.edit"))}</button><button data-club-runners="${c.id}">${escape(t('club.runners'))}</button>`])));
  $("master-categories").innerHTML = table(["category.code","category.name_en","category.name_de","master.events","common.active","common.details","common.edit"],pageRows('categories',directoryRows('categories'),'categories-pages').map(c => row([escape(c.code),escape(c.display_name_en),escape(c.display_name_de),categories.get(c.id)?.count||0,t(c.active ? "common.yes" : "common.no"),c.needs_review ? escape(t("category.review")) : "",`<button data-master-category="${c.id}">${escape(t("common.edit"))}</button>`])));
}
function render() {
  const s = snapshot, e = s.event;
  document.title = `FoxLive — ${e?.name || t("app.subtitle")}`;
  $("event-select").innerHTML = s.events.map(v => `<option value="${v.id}" ${v.id === selected ? "selected" : ""}>${escape(v.name)} — ${escape(status("event",v.state))}</option>`).join("") || `<option>${escape(t("event.none"))}</option>`;
  $("event-title").textContent = e?.name || t("event.begin"); $("event-description").textContent = e?.description || "";
  $("event-context").textContent=e?.name||t('event.begin'); $("event-context-date").textContent=e?new Intl.DateTimeFormat(UI.locale(lang),{year:'numeric',month:'2-digit',day:'2-digit',timeZone:'UTC'}).format(new Date(e.date+'T12:00Z')):'';
  $("event-state").textContent = e ? `${status("event",e.state)} · ${status("timing",e.timing_mode)}${s.active_event_id && s.active_event_id !== e.id ? " · " + t("event.other_running") : ""}` : t("event.none");
  $("connection").textContent = `${t("source.label")}: ${t(s.application.serial_enabled ? s.application.source_connected === null ? "source.connecting" : s.application.source_connected ? "source.connected" : "source.disconnected" : "source.offline")}`;
  $("sync").textContent = `${t("source.sync")}: ${t(!s.application.time_sync_enabled ? "source.sync_disabled" : s.diagnostics.timesync ? s.diagnostics.timesync.success ? "source.sync_ok" : "source.sync_failed" : "source.sync_none")}`;
  $("socket").textContent = `${t("source.updates")}: ${t(socketConnected ? "source.live" : "source.reconnecting")}`;
  if (s.processing_error) error(problem('error.processing'));
  $("system-status").innerHTML=technical({application:s.application,diagnostics:s.diagnostics,error:s.processing_error}); $("base-status").innerHTML=technical({source:s.application.source_port,connection:s.diagnostics.connection,time_sync:s.diagnostics.timesync});
  workspace?.context(e); document.querySelectorAll('#open-display,[data-display-link]').forEach(link => link.href='/live/display'+(e?'?event_id='+e.id:''));
  if (s.application.serial_enabled && s.application.source_connected === false && capture.waiting) cancelTag("rfid.no_connection");
  const participants = new Map(s.participants.map(p => [p.id,p])), categories = new Map(s.categories.map(c => [c.id,c])), results = new Map(s.results.map(r => [r.participant_id,r]));
  $("recent").innerHTML = table(["time.local","station.label","participant.label","category.label","punch.status","punch.signal","common.actions"], s.recent.map(p => row([
    escape(time(p.station_timestamp)), escape(stationName(p)), p.participant_id ? `<button data-detail="${p.participant_id}">#${p.start_number} ${escape(p.first_name)} ${escape(p.last_name)}</button>` : `${escape(t("rfid.unknown"))} ${escape(p.uid)}`,
    escape(p.category), escape(status("punch",p.status)), escape(p.rssi), `<button data-exclude="${p.id}">${escape(t("punch.exclude"))}</button>`
  ])));
  $("unknown").innerHTML = table(["rfid.label","station.label","time.local","rfid.assign"], s.unknown.map(p => row([
    escape(p.uid), escape(stationName(p)), escape(time(p.station_timestamp)), `<button data-register-tag="${p.id}" data-uid="${escape(p.uid)}">${escape(t("rfid.assign_or_register"))}</button>`
  ])).slice(0,20));
  const resultRow = r => { const p = participants.get(r.participant_id); return row([
    escape(r.rank ?? "—"), p?.start_number, `<button data-detail="${p?.id}">${escape(p?.first_name)} ${escape(p?.last_name)}</button>`, r.controls, escape(status("participant",r.status)),
    r.status === "RUNNING" && r.start !== null ? `<span data-running-start="${r.start}">${duration(Math.max(0,Math.floor(Date.now()/1000)-r.start))}</span> (${escape(t("ranking.provisional_note"))})` : duration(r.elapsed), escape(time(r.start)), escape(time(r.finish))
  ]); };
  const rankingHeaders = ["ranking.rank","participant.start_number","participant.label","ranking.controls","participant.status","time.elapsed","time.start","time.finish"];
  $("rankings").innerHTML = s.categories.map(c => { const group = s.results.filter(r => r.category_id === c.id); return `<h4>${escape(categoryLabel(c))}${c.active ? "" : " · " + escape(t("common.inactive"))}</h4><h5>${escape(t("ranking.finished"))}</h5>${table(rankingHeaders,group.filter(r => r.rank !== null).map(resultRow))}<h5>${escape(t("ranking.provisional"))}</h5>${table(rankingHeaders,group.filter(r => r.rank === null).map(resultRow))}`; }).join("") || escape(t("category.none"));
  renderParticipants();
  const enabled=new Map(s.categories.map(c=>[c.id,c]));
  $("categories").innerHTML=masters.categories.map(c => `<label class="category-choice"><input type="checkbox" data-category-toggle="${c.id}" ${enabled.get(c.id)?.enabled?'checked':''} ${e?.state==='ARCHIVED'||(!c.active&&!enabled.has(c.id))?'disabled':''}><span>${escape(categoryLabel(enabled.get(c.id)||c))}${!c.active?' · '+escape(t('common.inactive')):''}</span></label>`).join('')||`<p>${escape(t('category.none'))}</p>`;
  $("station-list").innerHTML = table(["station.number","common.name","station.role","common.enabled","station.count","station.last_time","station.callsign","punch.signal","common.edit"],s.stations.map(v => row([
    v.station_id,escape(v.display_name),escape(status("station",v.role)),t(v.enabled ? "common.yes" : "common.no"),v.punch_count || 0,escape(time(v.last_time)),escape(v.callsign),escape(v.rssi),`<button data-edit-station="${v.station_id}">${escape(t("common.edit"))}</button>`
  ])));
  $('activity').innerHTML=table(['station.label','station.count','station.last_time'],s.stations.map(v=>row([escape(v.display_name),v.punch_count||0,escape(time(v.last_time))])));
  $("export-participants").href = e ? `/api/events/${e.id}/export/participants` : "#"; $("export-results").href = e ? `/api/events/${e.id}/export/results` : "#";
  document.querySelectorAll("[data-state]").forEach(button => button.disabled = !e || e.state === "ARCHIVED");
  tagView(); tick();
  renderMasters();
}
function renderParticipants() {
  if(!snapshot) return; const s=snapshot, categories=new Map(s.categories.map(c=>[c.id,c])), results=new Map(s.results.map(r=>[r.participant_id,r]));
  const filter=$('participant-category-filter'),old=filter.value;
  filter.innerHTML=`<option value="">${escape(t('common.all'))}</option>`+s.categories.map(c=>`<option value="${c.id}">${escape(categoryLabel(c))}</option>`).join(''); filter.value=old;
  const words=FoxLiveCombo.tokens($('participant-search').value), state=$('participant-status-filter').value;
  const rows=s.participants.filter(p=>words.every(w=>`${p.start_number} ${p.first_name} ${p.last_name} ${p.birth_year||''} ${p.club} ${p.club_code} ${p.uid||''}`.toLocaleLowerCase().includes(w))&&(!filter.value||p.category_id===Number(filter.value))&&(!state||results.get(p.id)?.status===state));
  rows.sort((a,b)=>$('participant-sort').value==='name'?`${a.last_name} ${a.first_name}`.localeCompare(`${b.last_name} ${b.first_name}`)||a.start_number-b.start_number:a.start_number-b.start_number);
  $('participant-list').innerHTML=s.participants.length?table(['participant.start_number','common.name','runner.birth_year','club.label','category.label','rfid.label','participant.status','common.actions'],pageRows('participants',rows,'participant-pages').map(p=>row([p.start_number,escape(`${p.first_name} ${p.last_name}`),p.birth_year||'—',escape(p.club_code||p.club),escape(categoryLabel(categories.get(p.category_id))),`<button data-edit-participant="${p.id}">${escape(p.uid||t('rfid.assign'))}</button>`,escape(p.active?status('participant',results.get(p.id)?.status):t('common.inactive')),`<button data-edit-participant="${p.id}">${escape(t('registration.edit'))}</button><button data-detail="${p.id}">${escape(t('common.details'))}</button><button data-deactivate="${p.id}" ${!p.active?'disabled':''}>${escape(t('registration.deactivate'))}</button>`]))):`<p class="empty-state">${escape(t('registration.empty'))}</p>`;
}
function tick() {
  $("clock").textContent = `${zone()}: ${UI.dateTime(Date.now()/1000,zone(),lang)}`;
  document.querySelectorAll("[data-running-start]").forEach(e => e.textContent = duration(Math.max(0,Math.floor(Date.now()/1000)-Number(e.dataset.runningStart))));
}
function translatePage() {
  t = UI.translator(catalogs,lang); document.documentElement.lang = lang; $("language").value = lang;
  document.querySelectorAll("[data-i18n]").forEach(e => e.textContent = t(e.dataset.i18n));
  document.querySelectorAll("[data-i18n-aria]").forEach(e => e.setAttribute("aria-label",t(e.dataset.i18nAria)));
  document.querySelectorAll("input,select,textarea").forEach(e => { if (e.validity.customError) { e.setCustomValidity(""); if (!e.validity.valid) e.setCustomValidity(nativeMessage(e)); } });
  if (snapshot) render(); timeCaptions(); tagView(); renderTags(); renderAudit(); renderMasterAudit(); renderSources(); renderImport(); error(lastError);
}
$("language").onchange = event => { lang = UI.remember(preferences,event.target.value); translatePage(); if (detailId) showDetail(detailId).catch(error); };
function cancelTag(notice = null) { captureGeneration++; capture.cancel(); tagNotice = notice; tagView(); }
const context = () => `${selected}:${$("participant-form").dataset.entityId || "new"}:${field($("participant-form"),"start_number").value}`;
function tagDescription(tag) {
  return t("rfid.detected_at", {uid:tag.uid,station:stationName(tag),time:tag.station_time_valid ? time(tag.station_timestamp) : t("time.unsynchronized")}) + " · " + t("rfid.received",{time:time(tag.received_at)});
}
function tagView() {
  if (!t) return;
  $("assigned-tag").textContent = field($("participant-form"),"uid").value || t("rfid.none");
  $("tag-panel").hidden = !capture.waiting && !capture.detected && !tagNotice;
  $("confirm-tag").hidden = !capture.detected;
  $("tag-status").textContent = capture.waiting ? t("rfid.waiting") : capture.detected ? `${t("rfid.detected")}: ${tagDescription(capture.detected)}` : tagNotice ? t(tagNotice) : "";
  $("read-tag").disabled = capture.waiting || snapshot?.event?.state === "ARCHIVED";
}
async function loadTags() {
  if (!selected) { recentTags = []; return; }
  const choice = selected, result = await api(requireEvent()+"/rfid-candidates");
  if (choice !== selected) return;
  recentTags = result.items;
  renderTags();
}
function renderTags() {
  if (!t) return;
  const picker = $("recent-tags"), old = picker.value;
  picker.innerHTML = `<option value="">${escape(t(recentTags.length ? "rfid.choose_tag" : "rfid.no_recent"))}</option>` + recentTags.map(tag => `<option value="${tag.id}">${escape(tagDescription(tag))}</option>`).join(""); picker.value = old;
}
$("read-tag").onclick = action(async () => {
  requireEvent(); if (!$("participant-form").reportValidity()) return;
  if (snapshot.application.serial_enabled && !snapshot.application.source_connected) throw problem("rfid.no_connection");
  cancelTag(); const generation = captureGeneration, ctx = context();
  const baseline = await api(requireEvent()+"/rfid-candidates");
  if (generation !== captureGeneration || ctx !== context()) return;
  capture.arm(baseline.cursor,ctx); captureStarted = Date.now(); tagNotice = null; tagView();
});
async function pollTag() {
  if (!capture.waiting || polling) return;
  if (capture.context !== context()) { cancelTag(); return; }
  if (Date.now()-captureStarted > 120000) { cancelTag("rfid.timed_out"); return; }
  polling = true; const generation = captureGeneration;
  try {
    const batch = await api(requireEvent()+"/rfid-candidates?after_id="+capture.cursor);
    if (generation === captureGeneration) { capture.observe(batch,context()); tagView(); }
  } catch (e) { cancelTag(); error(e); } finally { polling = false; }
}
$("cancel-tag").onclick = () => cancelTag();
$("recent-tags").onchange = event => {
  const tag = recentTags.find(v => v.id === Number(event.target.value)); cancelTag();
  if (tag) { capture.choose(tag,context()); tagView(); }
};
function confirmAssignment(uid, data, oldUid) {
  const owner = snapshot.participants.find(p => p.active && p.uid === uid && String(p.id) !== $("participant-form").dataset.entityId);
  if (owner) throw problem("error.uid_assigned",{uid,number:owner.start_number});
  let question = t("rfid.confirm_message",{uid,number:data.start_number,name:`${data.first_name} ${data.last_name}`});
  if (oldUid && oldUid !== uid) question += "\n\n" + t("rfid.replace_message",{old_uid:oldUid});
  return confirm(question);
}
async function saveParticipant(tag = null) {
  const form = $("participant-form"); if (!form.reportValidity()) return;
  const ctx = context(), data = formData(form), id = form.dataset.entityId;
  data.category_id = Number(data.category_id); data.runner_id = Number(data.runner_id); data.uid = tag?.uid || data.uid || null; data.manual_status ||= null;
  const person = newPerson ? personData() : masters.runners.find(r => r.id === data.runner_id);
  if (!person) throw problem("runner.choose");
  if (!data.category_id) throw problem('category.choose');
  if (newPerson && runnerReviewed!==JSON.stringify(person)) {
    pendingRunnerMatches=await api('/api/ui/runner-matches',person);
    if (pendingRunnerMatches.length) { $('person-matches').hidden=false; $('person-matches').innerHTML=`<p>${escape(t('runner.possible_matches'))}</p>`+pendingRunnerMatches.map(r=>`<button type="button" data-use-runner="${r.id}">${escape(t('common.use_existing'))}: ${escape(runnerLabel(r))}</button>`).join('')+`<button type="button" id="runner-anyway">${escape(t('runner.create_anyway'))}</button>`; return; }
  }
  await dates(form,data,zone());
  if (ctx !== context()) return;
  const oldUid = snapshot.participants.find(p => String(p.id) === id)?.uid;
  if (tag && !confirmAssignment(tag.uid,{...data,...person},oldUid)) return;
  if (!tag && oldUid && oldUid !== data.uid && !confirm(t("rfid.replace_message",{old_uid:oldUid}))) return;
  if (tag) data.checked_in = true;
  let saved;
  if (newPerson) {
    if (id) throw problem("registration.new_only");
    delete data.runner_id;
    saved = await api(requireEvent()+"/register-new-runner",{runner:person,entry:data,club:stagedClub?.data||null,allow_similar_club:stagedClub?.allow_similar||false}); stagedClub=null; mastersDirty = true; await loadMasters();
  } else { saved = await api(requireEvent()+"/participants"+(id ? "/"+id : ""),data,id ? "PUT" : "POST"); mastersDirty=true; }
  setNewPerson(false); renderMasters(); cancelTag(tag ? "rfid.assigned" : null); populate(form,saved);
}
async function confirmCaptured() {
  const tag = capture.detected, ctx = context(), generation = captureGeneration;
  if (!tag || capture.context !== ctx) throw problem("rfid.stale");
  // Recheck availability at confirmation. The existing atomic participant update is authoritative.
  const batch = await api(requireEvent()+"/rfid-candidates?after_id="+(tag.id-1));
  if (ctx !== context() || generation !== captureGeneration) throw problem("rfid.stale");
  if (!batch.items.some(v => v.uid === tag.uid)) { cancelTag(); throw problem("rfid.other_owner"); }
  await saveParticipant(tag);
}
$("confirm-tag").onclick = action(confirmCaptured);
field($("participant-form"),"uid").addEventListener("input", () => { cancelTag(); tagView(); });
function registrationChanged() { const tag = capture.detected; cancelTag(); if (tag) { capture.choose(tag,context()); tagView(); } }
field($("participant-form"),"start_number").addEventListener("input", registrationChanged);
async function changeEvent(id) {
  cancelTag(); selected = id; detailId = null; $("detail").close(); $('registration-dialog').close();
  stagedClub=null; enablingCategory=null; $('category-enable').hidden=true; $('unknown-entry-panel').hidden=true; $('person-matches').hidden=true;
  auditRows = sourceRows = importSummary = null; resetForm($("participant-form")); setNewPerson(false); resetForm($("category-form")); resetForm($("station-form"));
  await refresh(); if (snapshot?.event) populate($("event-form"),snapshot.event); renderAudit(); renderSources(); renderImport();
}
$("event-select").onchange = action(async event => { await changeEvent(Number(event.target.value)||null); workspace.go('overview'); });
function defaultZone() {
  if (snapshot?.event) return snapshot.event.timezone;
  try { return preferences.getItem("foxlive.timezone") || Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC"; } catch { return "UTC"; }
}
function newEvent() {
  resetForm($("event-form")); const tz = defaultZone(); field($("event-form"),"timezone").value = tz;
  field($("event-form"),"date").value = UI.localInput(new Date().toISOString(),tz).slice(0,10); timeCaptions();
}
$("event-form").onsubmit = action(async () => {
  const form = $("event-form"), data = formData(form), id = form.dataset.entityId;
  await dates(form,data,data.timezone);
  if (id) { const old = snapshot.events.find(e => e.id === Number(id)); data.minimum_unix_timestamp = old.minimum_unix_timestamp; data.maximum_receive_skew_seconds = old.maximum_receive_skew_seconds; }
  const saved = await api(id ? `/api/events/${id}` : "/api/events",data,id ? "PUT" : "POST");
  if (selected !== saved.id) { cancelTag(); resetForm($("participant-form")); } selected = saved.id; populate(form,saved);
  mastersDirty=true; workspace.event=saved; workspace.go('overview');
  try { preferences.setItem("foxlive.timezone",saved.timezone); } catch { /* Optional preference. */ }
});
$("new-event").onclick = newEvent;
document.querySelectorAll("[data-state]").forEach(b => b.onclick = action(() => { if (['CLOSED','ARCHIVED'].includes(b.dataset.state)&&!confirm(t('event.confirm_state',{state:status('event',b.dataset.state)}))) return; return api(requireEvent()+"/state",{state:b.dataset.state}); }));
$("recalculate").onclick = action(async () => { const counts = await api(requireEvent()+"/recalculate",{}); importSummary = {recalculation:counts}; renderImport(); });
$("category-form").onsubmit = action(async () => {
  const form = $("category-form"), id = form.dataset.entityId;
  const data = formData(form); data.category_id = Number(data.category_id);
  await api(requireEvent()+"/categories"+(id ? "/"+id : ""),data,id ? "PUT" : "POST"); resetForm(form);
});
$("new-category").onclick = () => resetForm($("category-form"));
$("participant-form").onsubmit = action(() => saveParticipant());
function setNewPerson(value) {
  newPerson = value; $("new-runner-fields").hidden = !value; field($("participant-form"),"runner_id").disabled = value;
  $("new-runner-fields").querySelectorAll("input,select").forEach(input => { input.disabled = !value; input.required = value && ["first_name","last_name"].includes(input.dataset.person); });
  combos.runner.input.disabled=value;
}
function personData() {
  const data = {};
  $("new-runner-fields").querySelectorAll("[data-person]").forEach(input => data[input.dataset.person] = input.value || null);
  data.birth_year = data.birth_year ? Number(data.birth_year) : null;
  data.club_id = data.club_id && data.club_id!=='pending' ? Number(data.club_id) : null;
  if (!data.birth_year && !data.birth_date) throw problem("runner.birth_required");
  return data;
}
function openRegistration() { if (!selected) { error(problem('error.select_event')); return; } workspace.go('participants'); if (!$('registration-dialog').open) $('registration-dialog').showModal(); }
function newRegistration() { cancelTag(); stagedClub=null; enablingCategory=null; runnerReviewed=''; $('category-enable').hidden=true; $('person-matches').hidden=true; $('unknown-entry-panel').hidden=true; resetForm($("participant-form")); setNewPerson(false); renderRunners(); tagView(); openRegistration(); }
$("new-participant").onclick = newRegistration;
$("register-participant").onclick = newRegistration;
$("close-registration").onclick = () => {cancelTag(); stagedClub=null; $('registration-dialog').close();};
$('registration-dialog').addEventListener('cancel',()=>{cancelTag(); stagedClub=null;});
$('show-import').onclick=()=>{$('import-panel').hidden=!$('import-panel').hidden;};
$("create-runner").onclick = () => { if ($("participant-form").dataset.entityId) { error(problem("registration.new_only")); return; } registrationChanged(); setNewPerson(true); };
$("select-runner").onclick = () => { registrationChanged(); setNewPerson(false); };
document.querySelectorAll('[data-directory-search]').forEach(input=>input.oninput=()=>{pageNumbers[input.dataset.directorySearch]=0;renderMasters();});
for(const id of ['participant-search','participant-category-filter','participant-status-filter','participant-sort']) $(id).addEventListener(id==='participant-search'?'input':'change',()=>{pageNumbers.participants=0;renderParticipants();});
document.addEventListener('comboerror',event=>error(event.detail));
document.querySelectorAll('[data-close-dialog]').forEach(button=>button.onclick=()=>$(button.dataset.closeDialog).close());
$('close-master-detail').onclick=()=>$('master-detail').close();
function initCombos() {
  const make=(key,config)=>combos[key]=new FoxLiveCombo(document.querySelector(`[data-combo="${key}"]`),{text:key=>t(key),...config});
  make('runner',{items:()=>{const registered=new Set(snapshot?.participants.filter(p=>p.active&&String(p.id)!==$('participant-form').dataset.entityId).map(p=>p.runner_id));return masters.runners.filter(r=>r.active&&!registered.has(r.id)||r.id===combos.runner?.selected?.id);},label:runnerLabel,choose:()=>{registrationChanged();},create:value=>{ $('create-runner').click(); if(!value) return; const parts=value.includes(',')?value.split(',').map(p=>p.trim()).reverse():value.split(/\s+/); const first=$('new-runner-fields').querySelector('[data-person=first_name]'),last=$('new-runner-fields').querySelector('[data-person=last_name]'); if(!first.value&&!last.value){first.value=parts.shift()||'';last.value=parts.join(' ');} }});
  for(const key of ['registration-club','master-club']) make(key,{items:()=>masters.clubs.filter(c=>c.active||c.id===combos[key]?.selected?.id),label:clubLabel,choose:()=>{if(key==='registration-club') stagedClub=null;},create:value=>openClub(key,value)});
  make('registration-category',{items:()=>{const enabled=(snapshot?.categories||[]).filter(c=>c.enabled);const ids=new Set(enabled.map(c=>c.id));return [...enabled,...masters.categories.filter(c=>c.active&&!ids.has(c.id))];},label:c=>categoryLabel(c)+((snapshot?.categories.find(v=>v.id===c.id)?.enabled)?'':' · '+t('category.not_enabled')),choose:c=>{if(!snapshot.categories.find(v=>v.id===c.id)?.enabled){enablingCategory=c;combos['registration-category'].set(null);$('category-enable').hidden=false;$('category-enable').querySelector('p').textContent=categoryLabel(c)+' · '+t('category.not_enabled');}},create:openCategory});
  make('event-category',{items:()=>masters.categories,label:categoryLabel,create:openCategory});
  make('unknown-entry',{items:()=>snapshot?.participants.filter(p=>p.active)||[],label:p=>`#${p.start_number} ${p.first_name} ${p.last_name}`,choose:()=>{}});
  for(const [key,actionKey] of Object.entries({runner:'runner.new','registration-club':'club.quick_heading','master-club':'club.quick_heading','registration-category':'category.create','event-category':'category.create'})) combos[key].root.dataset.combosAction=actionKey;
}
function openClub(target,value='') {
  clubTarget=target; clubReviewed=false; $('club-matches').hidden=true;
  $('quick-club').querySelector('[data-club=code]').value=value.trim(); $('quick-club').querySelector('[data-club=display_name]').value='';
  $('club-dialog').showModal(); error(null);
}
function clubData() {const values={};$('quick-club').querySelectorAll('[data-club]').forEach(input=>values[input.dataset.club]=input.value.trim()); if(!values.display_name) values.display_name=values.code; if(!values.display_name) throw problem('error.club_blank');return values;}
function clubReview(matches) {
  $('club-matches').hidden=false; $('club-matches').innerHTML=`<p>${escape(t(matches.exact.length?'club.exact_match':'club.similar_matches'))}</p>`+[...matches.exact,...matches.similar].map(c=>`<button type="button" data-use-club="${c.id}">${escape(t('common.use_existing'))}: ${escape(clubLabel(c))}</button>`).join('')+(matches.exact.length?'':`<button type="button" id="club-anyway">${escape(t('club.create_anyway'))}</button>`);
}
async function createClub() {
  const data=clubData(),matches=await api('/api/ui/club-matches',data);
  if(matches.exact.length||(matches.similar.length&&!clubReviewed)){clubReview(matches);return;}
  if(clubTarget==='registration-club') {stagedClub={data,allow_similar:clubReviewed}; combos[clubTarget].set({id:'pending',...data});}
  else {const club=await api('/api/ui/quick-club',{club:data,allow_similar:clubReviewed});mastersDirty=true;await loadMasters();if(clubTarget==='club-form') resetForm($('club-form'));else combos[clubTarget].set(club);}
  $('club-dialog').close();
}
$('create-select-club').onclick=action(createClub);
$('quick-club').addEventListener('input',()=>{clubReviewed=false;$('club-matches').hidden=true;});
function openCategory(value='') {
  requireEvent(); $('quick-category').querySelectorAll('[data-category]').forEach(input=>input.value=input.dataset.category==='code'?value.trim():'');
  $('category-dialog').showModal(); error(null);
}
$('event-create-category').onclick=()=>{try{openCategory();}catch(e){error(e);}};
$('create-enable-category').onclick=action(async()=>{
  const data={};$('quick-category').querySelectorAll('[data-category]').forEach(input=>data[input.dataset.category]=input.value.trim());
  const saved=await api(requireEvent()+'/quick-category',data);mastersDirty=true;await loadMasters();combos['registration-category'].set(saved);$('category-enable').hidden=true;$('category-dialog').close();
});
$('enable-category').onclick=action(async()=>{
  const category=enablingCategory;if(!category)return;const saved=await api(requireEvent()+'/categories',{category_id:category.id,enabled:true});combos['registration-category'].set(saved);$('category-enable').hidden=true;mastersDirty=true;
});
$('use-existing-entry').onclick=()=>{
  const entry=combos['unknown-entry'].selected,tag=capture.detected;if(!entry){error(problem('rfid.choose_participant'));return;}
  setNewPerson(false);populate($('participant-form'),entry);$('unknown-entry-panel').hidden=true;if(tag){capture.choose(tag,context());tagView();}
};
document.body.addEventListener('click',event=>{
  const button=event.target.closest('button');if(!button)return;
  if(button.dataset.page){pageNumbers[button.dataset.page]=(pageNumbers[button.dataset.page]||0)+Number(button.dataset.delta);render();}
  if(button.dataset.useClub){const club=masters.clubs.find(c=>c.id===Number(button.dataset.useClub));if(club){stagedClub=null;if(clubTarget==='club-form') populate($('club-form'),club);else combos[clubTarget].set(club);$('club-dialog').close();}}
  if(button.id==='club-anyway'){clubReviewed=true;action(createClub)(event);}
  if(button.dataset.useRunner){const runner=masters.runners.find(r=>r.id===Number(button.dataset.useRunner));if(runner){setNewPerson(false);stagedClub=null;combos.runner.set(runner);$('person-matches').hidden=true;}}
  if(button.id==='runner-anyway'){runnerReviewed=JSON.stringify(personData());$('person-matches').hidden=true;action(capture.detected?confirmCaptured:()=>saveParticipant())(event);}
});
for (const [formId,path] of [["runner-form","/api/runners"],["club-form","/api/clubs"],["master-category-form","/api/master/categories"]]) {
  $(formId).onsubmit = action(async () => { const form = $(formId), data = formData(form), id = form.dataset.entityId;
    if (formId === "runner-form") { data.birth_year ||= null; data.birth_date ||= null; data.club_id = data.club_id ? Number(data.club_id) : null; }
    if (formId==='club-form' && !id) { const matches=await api('/api/ui/club-matches',data); if(matches.exact.length||matches.similar.length){openClub('club-form',data.code);$('quick-club').querySelector('[data-club=display_name]').value=data.display_name;clubReview(matches);return;} }
    await api(path + (id ? "/"+id : ""),data,id ? "PUT" : "POST"); mastersDirty = true; resetForm(form);
  });
}
document.querySelectorAll("[data-reset]").forEach(button => button.onclick = () => resetForm($(button.dataset.reset)));
function renderMasterAudit() { if (!t || !masterAuditRows) return; $("master-audit").innerHTML = table(["time.local","history.operator","history.action","debug.details"],masterAuditRows.map(r => row([escape(time(r.created_at)),escape(r.operator),escape(t("master."+r.action)),technical(r)]))); }
$("load-master-audit").onclick = action(async () => { masterAuditRows = await api("/api/master/audit"); renderMasterAudit(); });
$("station-form").onsubmit = action(async () => { const data = formData($("station-form")); await api(requireEvent()+"/stations/"+data.station_id,data,"PUT"); });
$("import-form").onsubmit = action(async event => {
  const commit = event.submitter?.value === "commit";
  importSummary = await api(requireEvent()+"/import",{text:field($("import-form"),"text").value,commit}); importSummary.committed = commit; renderImport();
});
function renderImport() {
  if (!t) return; if (!importSummary) { $("import-summary").replaceChildren(); return; }
  if (importSummary.recalculation) { $("import-summary").textContent = t("result.counts",{count:importSummary.recalculation.source || importSummary.recalculation.source_punches || 0}); return; }
  const v = importSummary;
  $("import-summary").innerHTML = `<p>${escape(t(v.committed && v.valid ? "csv.imported" : "csv.summary",{count:v.count}))}</p>` +
    (v.errors.length ? table(["csv.row","csv.error"],v.errors.map(e => row([e.row,escape(e.ui_error?.[lang] || e.error)]))) : "") +
    (v.entries ? table(["participant.start_number","common.name","category.label","rfid.label","time.start"],v.entries.map(p => row([p.start_number,escape(`${p.first_name} ${p.last_name}`),escape(categoryLabel(snapshot.categories.find(c => c.id === p.category_id))),escape(p.uid),escape(time(p.start_time))]))) : "");
}
$("csv-file").onchange = action(async event => {
  const file = event.target.files[0]; if (file?.size > 2000000) throw problem("error.csv_size");
  if (file) { try { field($("import-form"),"text").value = new TextDecoder("utf-8",{fatal:true}).decode(await file.arrayBuffer()); } catch { throw problem("csv.utf8"); } }
});
function renderSources() {
  if (!t || !sourceRows) { $("source-summary").replaceChildren(); return; }
  $("source-summary").innerHTML = table(["debug.select","rfid.label","station.label","time.local","debug.details"],sourceRows.map(p => row([
    `<input type="checkbox" data-source="${p.id}" ${p.replayed ? "disabled" : ""} aria-label="${escape(t("debug.select")+": "+p.uid+" · "+stationName(p)+" · "+time(p.station_timestamp))}">`,escape(p.uid),escape(stationName(p)),escape(time(p.station_timestamp)),technical(p)
  ])));
}
$("source-list").onclick = action(async () => { sourceRows = await api("/api/source-punches?limit=100"); renderSources(); });
$("associate-form").onsubmit = action(async () => {
  const ids = [...document.querySelectorAll("[data-source]:checked")].map(input => Number(input.dataset.source));
  if (!ids.length) throw problem("error.choice");
  if (confirm(t("debug.associate_confirm",{count:ids.length}))) await api(requireEvent()+"/associate",{punch_ids:ids});
});
function renderAudit() {
  if (!t || !auditRows) { $("audit-list").replaceChildren(); return; }
  $("audit-list").innerHTML = table(["time.local","history.operator","history.action","history.entity","history.reason","debug.details"],auditRows.map(r => {
    const data = r.after || r.before || {}, entity = data.start_number ? `#${data.start_number} ${data.first_name || ""} ${data.last_name || ""}` : data.code ? categoryLabel(data) : data.display_name || data.name || snapshot.event?.name || "—";
    return row([escape(time(r.created_at)),escape(r.operator),escape(t("history."+r.action.replace("after_close:","")))+(r.action.startsWith("after_close:") ? " · "+escape(t("history.after_close")) : ""),escape(entity),escape(r.reason),technical(r)]);
  }));
}
$("load-audit").onclick = action(async () => { requireEvent(); auditRows = await api(`/api/audit?event_id=${selected}`); renderAudit(); });
document.body.addEventListener("click", event => {
  const b = event.target.closest("button"); if (!b || !["editParticipant","editCategory","editStation","registerTag","masterRunner","masterClub","masterCategory","exclude","detail","deactivate","runnerHistory","clubRunners"].some(key => b.dataset[key])) return;
  action(async () => {
    if (b.dataset.masterRunner) populate($("runner-form"),masters.runners.find(r => r.id === Number(b.dataset.masterRunner)));
    if (b.dataset.masterClub) populate($("club-form"),masters.clubs.find(r => r.id === Number(b.dataset.masterClub)));
    if (b.dataset.masterCategory) populate($("master-category-form"),masters.categories.find(r => r.id === Number(b.dataset.masterCategory)));
    if (b.dataset.editParticipant) { cancelTag(); stagedClub=null; $('unknown-entry-panel').hidden=true; $('category-enable').hidden=true; $('person-matches').hidden=true; setNewPerson(false); populate($("participant-form"),snapshot.participants.find(p => p.id === Number(b.dataset.editParticipant))); openRegistration(); }
    if (b.dataset.editCategory) populate($("category-form"),snapshot.categories.find(c => c.id === Number(b.dataset.editCategory)));
    if (b.dataset.editStation) populate($("station-form"),snapshot.stations.find(s => s.station_id === Number(b.dataset.editStation)));
    if (b.dataset.registerTag) {
      newRegistration();
      const batch = await api(requireEvent()+"/rfid-candidates?after_id="+(Number(b.dataset.registerTag)-1));
      const tag = batch.items.find(v => v.uid === b.dataset.uid); if (!tag) throw problem("rfid.other_owner");
      capture.choose(tag,context()); tagView(); $('unknown-entry-panel').hidden=false;
    }
    if (b.dataset.deactivate) {
      const p=snapshot.participants.find(p=>p.id===Number(b.dataset.deactivate));if(!confirm(t('registration.confirm_deactivate',{number:p.start_number,name:`${p.first_name} ${p.last_name}`})))return;
      const data={};for(const key of ['runner_id','start_number','category_id','uid','start_time','manual_status','active','checked_in'])data[key]=p[key];data.active=false;await api(requireEvent()+'/participants/'+p.id,data,'PUT');mastersDirty=true;
    }
    if (b.dataset.runnerHistory) {
      const rows=await api('/api/runners/'+b.dataset.runnerHistory+'/history');$('master-detail-body').innerHTML=table(['event.label','event.date','participant.start_number','category.label','rfid.label'],rows.map(r=>row([escape(r.event_name),escape(new Intl.DateTimeFormat(UI.locale(lang),{timeZone:'UTC',dateStyle:'medium'}).format(new Date(r.event_date+'T12:00Z'))),r.start_number,escape(categoryLabel(r)),escape(r.uid)])));$('master-detail').showModal();
    }
    if (b.dataset.clubRunners) {const c=masters.clubs.find(c=>c.id===Number(b.dataset.clubRunners));document.querySelector('[data-directory-search=runners]').value=c.code||c.display_name;workspace.go('runners');renderMasters();}
    if (b.dataset.exclude) { const reason = prompt(t("punch.exclusion_reason")); if (reason) await api(requireEvent()+"/punches/"+b.dataset.exclude+"/exclude",{reason}); }
    if (b.dataset.detail) { detailId = Number(b.dataset.detail); await showDetail(detailId); if(!$('detail').open)$('detail').showModal(); }
  })(event);
});
async function showDetail(id) {
  const event = selected, data = await api(requireEvent()+"/participants/"+id), p = data.participant, r = data.result;
  if (event !== selected || detailId !== id) return;
  const category = snapshot.categories.find(c => c.id === p.category_id);
  $("detail-body").innerHTML = `<p>#${p.start_number} ${escape(p.first_name)} ${escape(p.last_name)} · ${escape(p.club)} · ${escape(categoryLabel(category))} · ${escape(p.uid || t("rfid.none"))} · ${escape(status("participant",r.status))} · ${escape(t("ranking.controls"))}: ${r.controls}</p><p>${escape(t("time.start"))}: ${escape(time(r.start))} · ${escape(t("time.finish"))}: ${escape(time(r.finish))} · ${escape(t("time.elapsed"))}: ${duration(r.elapsed)}</p>` +
    table(["time.local","station.label","punch.status","history.reason","punch.signal"],data.history.map(v => row([escape(time(v.station_timestamp)),escape(stationName(v)),escape(status("punch",v.status)),escape(v.reason === "Predefined start remains authoritative" ? t("punch.predefined_reason") : v.reason),escape(v.rssi)])));
}
$("close-detail").onclick = () => { detailId = null; $("detail").close(); };
$('detail').addEventListener('cancel',()=>{detailId=null;});
document.addEventListener('change',event=>{
  if(!event.target.dataset.categoryToggle)return;
  action(async()=>{const id=Number(event.target.dataset.categoryToggle),current=snapshot.categories.find(c=>c.id===id);await api(requireEvent()+'/categories',{category_id:id,enabled:event.target.checked,display_order:current?.display_order||0});mastersDirty=true;})(event);
});
function connect() {
  const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);
  ws.onopen = () => { socketConnected = true; mastersDirty = true; schedule(); };
  ws.onmessage = event => { if (["master_data_changed","snapshot","resync"].includes(JSON.parse(event.data).type)) mastersDirty = true; schedule(); pollTag(); };
  ws.onerror = () => ws.close();
  ws.onclose = () => { socketConnected = false; cancelTag(); if (snapshot) render(); setTimeout(connect,2000); };
}
async function start() {
  const [en,de] = await Promise.all([api("/static/translations/en.json"),api("/static/translations/de.json")]);
  catalogs = {en,de}; lang = preferences.getItem('foxlive.language') ? UI.preferred(preferences) : document.body.dataset.defaultLanguage || 'en'; translatePage(); initCombos();
  workspace=new FoxLiveWorkspace({text:key=>t(key),eventChanged:id=>changeEvent(id).catch(error),preferences}); selected=workspace.initialEvent();
  // A remembered event is a convenience, never a prerequisite for starting a new database.
  const events=await api('/api/events');if(!events.some(e=>e.id===selected))selected=null;
  await refresh(); workspace.read();
  if (snapshot?.event) populate($("event-form"),snapshot.event); else newEvent();
  startupControls.forEach(control => control.disabled = false); setNewPerson(false); if (snapshot) render();
  setInterval(tick,1000); setInterval(pollTag,750); connect();
}
start().catch(e => { $("error").textContent = e.message || "FoxLive could not load its local presentation assets."; $("error").hidden = false; });
