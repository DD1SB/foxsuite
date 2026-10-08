"use strict";
window.FoxLiveWorkspace = class {
  constructor({text,eventChanged,preferences}) {
    Object.assign(this,{text,eventChanged,preferences,event:null,view:'overview'});
    this.groups = {event:['overview','participants','categories','stations','live','rankings'],master:['runners','clubs','master-categories'],system:['base','diagnostics','settings']};
    document.addEventListener('click',event => { const link=event.target.closest('[data-view-link]'); if (link && !event.ctrlKey && !event.metaKey && !event.shiftKey && event.button===0) { event.preventDefault(); this.go(link.dataset.viewLink); } });
    window.addEventListener('popstate',() => this.read());
  }
  initialEvent() { const found=location.pathname.match(/^\/events\/(\d+)\//); if (found) return Number(found[1]); try { return Number(this.preferences.getItem('foxlive.event')) || null; } catch { return null; } }
  path(view) { const group=this.group(view); return group==='event' ? this.event ? `/events/${this.event.id}/${view}` : '/live' : group==='master' ? '/master/'+(view==='master-categories'?'categories':view) : '/system/'+view; }
  group(view=this.view) { return Object.keys(this.groups).find(key => this.groups[key].includes(view)) || 'event'; }
  go(view,replace=false) { this.view=view; history[replace?'replaceState':'pushState']({},'',this.path(view)); this.render(); }
  read() {
    const parts=location.pathname.split('/');
    this.view=parts[1]==='events'?parts[3]:parts[1]==='master'?(parts[2]==='categories'?'master-categories':parts[2]):parts[1]==='system'?parts[2]:'overview';
    if (!Object.values(this.groups).flat().includes(this.view)) this.view='overview';
    const id=parts[1]==='events'?Number(parts[2]):this.event?.id;
    if (id && id!==this.event?.id) this.eventChanged(id); else this.render();
  }
  context(event) { this.event=event; if (event) { try { this.preferences.setItem('foxlive.event',event.id); } catch {} }
    if (location.pathname==='/' || location.pathname==='/live') history.replaceState({},'',this.path(this.view)); this.render();
  }
  render() {
    const group=this.group(); document.querySelectorAll('[data-view]').forEach(panel => panel.hidden=panel.dataset.view!==this.view);
    const sub=document.getElementById('sub-nav'); sub.replaceChildren();
    this.groups[group].forEach(view => { const link=document.createElement('a'); link.href=this.path(view); link.dataset.viewLink=view; link.textContent=this.text('view.'+view); if(view===this.view) link.setAttribute('aria-current','page'); sub.append(link); });
    document.querySelectorAll('[data-view-link]').forEach(link => link.href=this.path(link.dataset.viewLink));
    document.querySelectorAll('#top-nav a').forEach(link => { if(this.group(link.dataset.viewLink)===group) link.setAttribute('aria-current','page'); else link.removeAttribute('aria-current'); });
  }
};
