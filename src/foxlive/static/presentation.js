"use strict";
/* Shared, dependency-free presentation helpers. No competition or source mutation. */
globalThis.FoxLiveUI = (() => {
  const preference = "foxlive.language";
  const normalize = value => value === "de" ? "de" : "en";
  function preferred(storage) {
    try { return normalize(storage.getItem(preference)); } catch { return "en"; }
  }
  function remember(storage, lang) {
    try { storage.setItem(preference, normalize(lang)); } catch { /* Private browser mode. */ }
    return normalize(lang);
  }
  function translator(catalogs, lang) {
    return (key, values = {}) => {
      const text = catalogs[normalize(lang)]?.[key] ?? catalogs.en[key] ?? catalogs.en["common.unavailable"];
      return text.replace(/\{(\w+)\}/g, (_, name) => String(values[name] ?? "—"));
    };
  }
  const locale = lang => lang === "de" ? "de-DE" : "en-US";
  function dateTime(value, zone, lang) {
    if (value == null || value === "") return "—";
    const date = new Date(typeof value === "number" ? value * 1000 : value);
    if (Number.isNaN(date.getTime())) return "—";
    return new Intl.DateTimeFormat(locale(lang), {timeZone: zone, year:"numeric", month:"2-digit", day:"2-digit", hour:"2-digit", minute:"2-digit", second:"2-digit", hourCycle: "h23"}).format(date);
  }
  function localInput(value, zone) {
    if (!value) return "";
    const parts = new Intl.DateTimeFormat("en-CA", {timeZone: zone, year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23"}).formatToParts(new Date(value));
    const p = Object.fromEntries(parts.map(part => [part.type, part.value]));
    return `${p.year}-${p.month}-${p.day}T${p.hour}:${p.minute}:${p.second}`;
  }
  const categoryLabel = (category, lang = "en") => category ? `${category.code} – ${category[lang === "de" ? "display_name_de" : "display_name_en"] || category.display_name || category.display_name_en}` : "—";
  class TagCapture {
    constructor() { this.cancel(); }
    arm(cursor, context) { this.cursor = cursor; this.context = context; this.detected = null; this.waiting = true; }
    observe(batch, context) {
      if (!this.waiting || context !== this.context) return null;
      const found = batch.items.find(item => item.id > this.cursor);
      this.cursor = Math.max(this.cursor, batch.cursor);
      if (found) { this.detected = found; this.waiting = false; }
      return found ?? null;
    }
    choose(item, context) { this.cancel(); this.context = context; this.detected = item; }
    cancel() { this.cursor = 0; this.context = null; this.detected = null; this.waiting = false; }
  }
  return {preferred, remember, translator, locale, dateTime, localInput, categoryLabel, TagCapture};
})();
