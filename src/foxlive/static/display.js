"use strict";
/* Read-only projection of the existing result service. No registration or scoring writes. */
const UI = FoxLiveUI, preference = (()=>{try{return localStorage;}catch{return {getItem:()=>null,setItem:()=>{}};}})();
const $ = id => document.getElementById(id);
const target = new URLSearchParams(location.search).get("event_id");
const query = target ? `?event_id=${encodeURIComponent(target)}` : "";
let catalogs, lang = preference.getItem('foxlive.language') ? UI.preferred(preference) : document.body.dataset.defaultLanguage || 'en', state, connected = false, pending = false, again = false;
const t = (key, values) => UI.translator(catalogs, lang)(key, values);
const elapsed = value => value == null ? "—" : `${value >= 3600 ? Math.floor(value/3600)+":" : ""}${String(Math.floor(value%3600/60)).padStart(2,"0")}:${String(value%60).padStart(2,"0")}`;
function table(headers, rows) {
  if (!rows.length) { const p=document.createElement("p"); p.className="empty"; p.textContent=t("display.empty"); return p; }
  const table=document.createElement("table"), head=table.createTHead().insertRow(), body=table.createTBody();
  headers.forEach(key => { const th=document.createElement("th"); th.scope="col"; th.textContent=t(key); head.append(th); });
  rows.forEach(values => { const row=body.insertRow(); values.forEach(value => row.insertCell().textContent=value ?? "—"); });
  return table;
}
function render() {
  if (!catalogs) return;
  document.documentElement.lang=lang; $("language").value=lang;
  document.querySelectorAll("[data-i18n]").forEach(e=>e.textContent=t(e.dataset.i18n));
  $("fullscreen").textContent=t(document.fullscreenElement ? "display.exit_fullscreen" : "display.fullscreen");
  $("updates").textContent=t(connected ? "source.live" : "source.reconnecting");
  if (!state) return;
  const event=state.event, zone=event?.timezone || "Europe/Berlin";
  $("event-name").textContent=event?.name || "FoxLive";
  $("event-date").textContent=event ? `${new Intl.DateTimeFormat(UI.locale(lang),{dateStyle:"long",timeZone:"UTC"}).format(new Date(event.date+"T12:00:00Z"))} · ${t("event."+event.state)}` : t("event.none");
  $("summary").textContent=event ? `${t("display.running",{count:state.running})} · ${t("display.stations",{active:state.stations_active,total:state.stations_enabled})}` : "";
  $("notice").textContent=event ? "" : t("display.empty");
  const clock=timestamp => timestamp == null ? "—" : new Intl.DateTimeFormat(UI.locale(lang),{timeZone:zone,hour:"2-digit",minute:"2-digit",hourCycle:"h23"}).format(new Date(timestamp*1000));
  $("recent").replaceChildren(table(["time.local","station.label","participant.label","category.label"],state.recent.map(p=>[
    p.status==="INVALID_TIMESTAMP" ? t("time.unsynchronized") : clock(p.station_timestamp),
    p.station_name || t("station.fallback",{number:p.station_id}),
    p.participant_id ? `#${p.start_number} ${p.first_name} ${p.last_name}` : t("display.unknown"),
    state.categories.find(c=>c.id===p.category)?.code || p.category || "—"
  ])));
  const participants=new Map(state.participants.map(p=>[p.id,p]));
  const cards=[];
  state.categories.filter(c=>c.enabled || state.results.some(r=>r.category_id===c.id)).forEach(c=>{
    const section=document.createElement("section"), title=document.createElement("h3"); title.textContent=UI.categoryLabel(c,lang); section.append(title);
    const results=state.results.filter(r=>r.category_id===c.id);
    for (const [label, rows] of [["ranking.finished",results.filter(r=>r.rank!==null)],["ranking.provisional",results.filter(r=>r.rank===null)]]) {
      if (!rows.length) continue;
      const h=document.createElement("h4"); h.textContent=t(label); section.append(h);
      section.append(table(["ranking.rank","participant.label","ranking.controls","time.elapsed","participant.status"],rows.map(r=>{
        const p=participants.get(r.participant_id);
        const running=r.status==="RUNNING" && r.start!=null;
        return [r.rank, p ? `#${p.start_number} ${p.first_name} ${p.last_name}` : "—",r.controls,elapsed(running ? Math.max(0,Math.floor(Date.now()/1000)-r.start) : r.elapsed),t("participant."+r.status)+(r.completeness==='REVIEW_REQUIRED'?' · '+t('evidence.REVIEW_REQUIRED'):'')];
      })));
    }
    if (!results.length) section.append(table([],[]));
    cards.push(section);
  });
  $("rankings").replaceChildren(...cards);
}
async function refresh() {
  if (pending) { again=true; return; }
  pending=true;
  try { const response=await fetch("/api/display"+query); if (!response.ok) throw new Error(); state=await response.json(); render(); }
  catch { $("notice").textContent=t("error.network"); }
  finally { pending=false; if (again) { again=false; refresh(); } }
}
function connect() {
  const ws=new WebSocket(`${location.protocol==="https:" ? "wss" : "ws"}://${location.host}/ws/display${query}`);
  ws.onopen=()=>{connected=true; render(); refresh();};
  ws.onmessage=event=>{ const message=JSON.parse(event.data); if (message.type==="snapshot") {state=message.payload; render();} else refresh(); };
  ws.onerror=()=>ws.close(); ws.onclose=()=>{connected=false; render(); setTimeout(connect,2000);};
}
$("language").onchange=event=>{lang=UI.remember(preference,event.target.value); render();};
$("fullscreen").onclick=async()=>{try {if (document.fullscreenElement) await document.exitFullscreen(); else await document.documentElement.requestFullscreen();} catch { /* Browser policy may refuse fullscreen. */ }};
document.addEventListener("fullscreenchange",render);
Promise.all([fetch("/static/translations/en.json").then(r=>r.json()),fetch("/static/translations/de.json").then(r=>r.json())]).then(([en,de])=>{catalogs={en,de};render();refresh();connect();setInterval(render,1000);}).catch(()=>{$("notice").textContent="FoxLive unavailable";});
