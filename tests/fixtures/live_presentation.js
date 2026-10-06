"use strict";
// Runs the actual shipped browser helper without npm or a frontend build.
const assert = require("node:assert/strict"), fs = require("node:fs");
const root = process.argv[2], scenario = process.argv[3];
require(root + "/static/presentation.js");
const UI = globalThis.FoxLiveUI;
const catalogs = Object.fromEntries(["en","de"].map(lang => [lang,JSON.parse(fs.readFileSync(`${root}/static/translations/${lang}.json`,"utf8"))]));
if (scenario === "language") {
  const store = new Map(), storage = {getItem:key => store.get(key),setItem:(key,value) => store.set(key,value)};
  assert.equal(UI.preferred(storage),"en");
  assert.equal(UI.remember(storage,"de"),"de"); assert.equal(UI.preferred(storage),"de");
  assert.equal(UI.translator(catalogs,UI.preferred(storage))("participant.start_number"),"Startnummer");
  assert.equal(UI.remember(storage,"en"),"en"); assert.equal(UI.preferred(storage),"en");
  assert.equal(UI.translator(catalogs,UI.preferred(storage))("participant.start_number"),"Start number");
  assert.equal(UI.preferred({getItem:() => {throw Error();}}),"en");
} else if (scenario === "fallback") {
  const t = UI.translator({en:catalogs.en,de:{}},"de");
  assert.equal(t("participant.start_number"),"Start number");
  assert.equal(t("unknown.key"),"Unavailable");
} else if (scenario === "labels") {
  assert.equal(UI.categoryLabel({id:9123,code:"M40",display_name:"Männer 40"}),"M40 – Männer 40");
  assert.equal(UI.translator(catalogs,"de")("station.FINISH"),"Ziel");
  assert.equal(UI.translator(catalogs,"en")("participant.RUNNING"),"Running");
} else if (scenario === "dates") {
  const instant = "2026-10-06T12:30:00+00:00";
  assert.equal(UI.localInput(instant,"Europe/Berlin"),"2026-10-06T14:30:00");
  assert.match(UI.dateTime(instant,"Europe/Berlin","de"),/06\.10\.2026.*14:30/);
  assert.match(UI.dateTime(instant,"Europe/Berlin","en"),/10\/06\/2026.*14:30/);
  const foldA = "2026-10-25T00:30:00Z", foldB = "2026-10-25T01:30:00Z";
  assert.equal(UI.localInput(foldA,"Europe/Berlin"),UI.localInput(foldB,"Europe/Berlin"));
  assert.match(UI.dateTime("2026-10-06T22:30:00Z","Europe/Berlin","de"),/07\.10\.2026.*00:30/);
} else if (scenario === "capture") {
  const capture = new UI.TagCapture(); capture.arm(10,"event:participant");
  assert.equal(capture.observe({cursor:10,items:[{id:9,uid:"OLD"}]},"event:participant"),null);
  assert.equal(capture.observe({cursor:12,items:[{id:11,uid:"NEXT"}]},"other:event"),null);
  assert.equal(capture.observe({cursor:12,items:[{id:11,uid:"NEXT"},{id:12,uid:"LATER"}]},"event:participant").uid,"NEXT");
  assert.equal(capture.waiting,false); assert.equal(capture.detected.uid,"NEXT");
  assert.equal(capture.observe({cursor:13,items:[{id:13,uid:"LATER"}]},"event:participant"),null);
  capture.cancel(); assert.equal(capture.detected,null);
  capture.choose({id:8,uid:"RECENT"},"new"); assert.equal(capture.detected.uid,"RECENT");
}
