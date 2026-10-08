"use strict";
// One bounded, keyboard-operated widget shared by all person/club/category selections.
window.FoxLiveCombo = class {
  constructor(root, {items,label,choose,create,text}) {
    Object.assign(this,{root,items,label,choose,create,text,index:-1,rows:[]});
    this.input = root.querySelector('[role="combobox"]'); this.value = root.querySelector('input[type="hidden"]');
    this.popup = root.querySelector('.suggestions'); this.list = root.querySelector('[role="listbox"]');
    this.createButton = root.querySelector('[data-combo-create]');
    this.input.oninput = () => { this.value.value = ''; this.selected = null; this.rows=[]; this.index=-1; this.close(); clearTimeout(this.timer); this.timer = setTimeout(() => this.show(),120); };
    this.input.onfocus = () => this.show();
    this.input.onkeydown = event => {
      if (event.key === 'Escape' && !this.popup.hidden) { event.preventDefault(); event.stopPropagation(); this.close(); }
      if (['ArrowDown','ArrowUp'].includes(event.key)) { event.preventDefault(); if (this.popup.hidden) this.show(); this.index = Math.max(0,Math.min(this.rows.length-1,this.index+(event.key==='ArrowDown'?1:-1))); this.active(); }
      if (event.key === 'Enter') { event.preventDefault(); if(this.popup.hidden) this.show(); if (this.index >= 0 && this.rows[this.index]) this.pick(this.rows[this.index]); else if (this.rows.length===1) this.pick(this.rows[0]); }
      if (event.key === 'Tab' && !event.shiftKey && !this.popup.hidden && !this.createButton.hidden) { event.preventDefault(); this.createButton.focus(); }
      else if (event.key === 'Tab') this.close();
    };
    this.root.onfocusout = () => setTimeout(() => { if (!root.contains(document.activeElement)) this.close(); },0);
    this.createButton.onclick = () => { this.close(); this.create?.(this.input.value); };
  }
  static tokens(value) { return String(value).toLocaleLowerCase().replace(/[^\p{L}\p{N}]+/gu,' ').trim().split(/\s+/).filter(Boolean); }
  set(row) { this.selected = row || null; this.value.value = row?.id ?? ''; this.input.value = row ? this.label(row) : ''; this.close(); }
  update() { if (this.selected) this.input.value = this.label(this.selected); if (!this.popup.hidden) this.show(); }
  show() {
    if (this.input.disabled) return;
    const words = FoxLiveCombo.tokens(this.input.value);
    this.rows = this.items().filter(row => words.every(word => this.label(row).toLocaleLowerCase().includes(word))).slice(0,20);
    this.list.replaceChildren(); this.index = -1;
    this.rows.forEach((row,index) => {
      const option = document.createElement('div'); option.role = 'option'; option.id = this.list.id+'-'+index;
      option.textContent = this.label(row); option.setAttribute('aria-selected','false');
      option.onmousedown = event => event.preventDefault(); option.onclick = () => this.pick(row); this.list.append(option);
    });
    if (!this.rows.length) { const empty = document.createElement('p'); empty.textContent = this.text('combo.empty'); this.list.append(empty); }
    this.createButton.hidden = !this.create;
    this.createButton.textContent = this.text(this.root.dataset.combosAction || 'common.new');
    this.popup.hidden = false; this.input.setAttribute('aria-expanded','true'); this.input.removeAttribute('aria-activedescendant');
  }
  active() { [...this.list.children].forEach((option,i) => option.setAttribute('aria-selected',String(i===this.index))); const active = this.list.children[this.index]; if (active) { this.input.setAttribute('aria-activedescendant',active.id); active.scrollIntoView({block:'nearest'}); } }
  pick(row) { this.set(row); Promise.resolve(this.choose?.(row)).catch(error => this.root.dispatchEvent(new CustomEvent('comboerror',{bubbles:true,detail:error}))); }
  close() { this.popup.hidden = true; this.input.setAttribute('aria-expanded','false'); this.input.removeAttribute('aria-activedescendant'); }
};
