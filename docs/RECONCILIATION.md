# M5 evidence reconciliation

## Boundaries and deterministic policy

FoxCore punches remain immutable LIVE facts. Tag snapshots/records and manual
decisions are separate append-only facts. FoxLive caches a resolved view and
review cases; the existing timing and DistinctControlsThenTime strategy consume
that view. No tag/manual fact becomes a synthetic FoxCore punch.

Association is explicit to an event. The optional event `tag_event_id` must be
configured (uint16); unknown/null is not guessed. An active EventEntry resolves
the canonical UID. Historical events keep their own registrations and snapshots.

For each UID/file the latest attempted record is current evidence; previous
snapshots remain inspectable. Identical re-reads create sessions but not extra
scoring visits. A changed file supersedes its earlier observation for automatic
reconciliation, not for historical provenance. An incomplete read cannot remove
files not attempted. Missing files never invalidate valid live observations.

* An exact tag/live match is MATCHED; matching any of multiple legitimate live
  revisits is TAG_CONFIRMED_LIVE. Preserve all live visits and their first-visit
  timing semantics; tag overwrite is not corruption.
* Valid live alone remains LIVE_ONLY. A valid synchronized, correct-event tag
  observation without live evidence is TAG_ONLY_RECOVERED.
* Conflicting valid CONTROL or BEACON times keep the live history provisionally; station
  presence is not lost, but a review is open. No conflicting tag time silently
  replaces the live visit. For START/FINISH conflicting times are withheld from
  resolved timing until a reasoned choice; original observations remain visible.
* Wrong event, unknown event ID, malformed/failed file, nonzero reserved byte,
  unknown sync byte, unsynchronized time, invalid/pre-sync time, outside window
  and unknown/disabled station are retained, not automatically counted.
* LIVE duplicate/exclusion/invalidity classification remains unchanged. Valid
  tag evidence can recover a station despite an invalid live observation, but
  does not make that original observation valid.
* A tag timestamp matching an explicitly excluded live observation creates
  EXCLUDED_LIVE_MATCH review; it cannot silently undo the exclusion. A jury can
  explicitly select valid tag evidence or make a new ruling.
* A correct-event tag explicitly marked unsynchronized makes an equal-numbered
  live time untrusted in the resolved view too. The live source stays unchanged;
  matching invalid numbers never confirms timing. Other valid live visits remain
  usable. Wrong-event tag data does not invalidate current-event live evidence.

Tag time uses the event minimum/uint32/window guards, plus a future-clock guard
against PC read time. Historical offline punches are not rejected merely because
readout occurred long after the visit: radio receive-age validation applies only
to LIVE evidence. Failed sessions cannot automatically contribute their records;
good records in PARTIAL/ABORTED sessions can, with an incomplete-read review.

Resolved accepted observations use the existing earliest valid control/start and
finish-after-start logic. Readout time is never a replacement scoring timestamp.
Competition status and result completeness are independent: PROVISIONAL (no
successful readout), COMPLETE (review-free readout), REVIEW_REQUIRED (open case).
Completeness does not alter sporting ranks; unresolved timing cannot fabricate
an elapsed time. Public displays expose only a concise provisional indicator.
When offline observations tie within the same second, their private scoring
order is START, CONTROL/BEACON, FINISH, then stable source-record identity. No fractional
time is invented. All-live ties retain M3's original source-ID ordering. These
sort keys are not FoxCore IDs and are never persisted as source punches.

A later COMPLETE read resolves the prior incomplete-session case. The latest
attempt per file remains current even if malformed; earlier snapshots are kept
for review/export, not silently substituted. A later snapshot that never attempts
a file does not erase that file's previous evidence.

## Adjudication and provenance

An operator may choose a specific live/tag record, exclude a station, accept
CONTROL or BEACON presence without trusting time, add a manual whole-second observation,
or override timing with MANUAL evidence. Every action requires a reason and
records operator, before/after and timestamp in audit. Source timestamps are
never edited. CONTROL presence acceptance is an explicit exception to automatic
chronological timing checks and counts that station once; it cannot define
START/FINISH or elapsed time. BEACON presence acceptance records only beacon
presence, never a counted control. Manual BEACON time is allowed with the same
MANUAL provenance/reason/audit as other stations.

Decisions append, never replace/delete. AUTO supersedes a ruling and restores
automatic review. A decision references the evidence fingerprint it reviewed;
new/different evidence reopens review instead of silently inheriting an old
ruling. DNS/DNF/DSQ use the existing audited EventEntry status workflow.
The finish-desk jury action for DNS/DNF/DSQ (or return to automatic status) also
requires a reason and optional reviewer label. A manual observation without a
tag uses a private entry identity internally, never an invented RFID UID.
Fingerprints cover evidence, entry identity/start, timing/window/validity
configuration and station role/enabled state. Display-name, language, lifecycle
and ordering changes alone do not revoke rulings. A changed scoring input does.

Each resolved observation references its LIVE punch, TAG record or MANUAL
decision. Participant detail and evidence export retain all observations,
including superseded snapshots. Ordinary result export adds completeness,
recovered-control count, review and manual indicators, not raw bytes. The result
CSV also appends `beacon_punched`, without changing prior column order.
LIVE, CONFIRMED, RECOVERED and MANUAL summarize provenance; CONFIRMED means there
is corroborating tag evidence, not that every visit was proven by a complete tag
history. Readout summaries show the **current** reconciliation for that UID,
not a frozen result from the time of the selected historical snapshot.

Closing with open cases needs explicit confirmation. Closing does not destroy
or permanently freeze evidence; archive remains read-only. Recalculation/restart
rebuild derived state from associations, source facts and latest applicable
decisions without publishing old snapshots as newly arrived readouts.
Live/readout intake recalculates the affected UID and bulk category ranks;
configuration changes and explicit recalculation rebuild the full event. No UI
render triggers full recalculation. Source duplicate arrival does not invalidate
a decision fingerprint. Original/repeated captures stay individually auditable.

## ARDF beacon evidence

FoxLive station roles are CONTROL, START, BEACON and FINISH. BEACON (German Bake,
or Zielbake in explanatory text) is distinct from the finish line/FINISH station.
All generic evidence primitives retain that role, including raw timestamp/source
references, exclusion, manual selection, decisions and review/export.

| Evidence | Resolution | Sporting effect |
| --- | --- | --- |
| Matching valid LIVE/TAG beacon | MATCHED | Beacon presence; no extra control or timing endpoint |
| Tag matches a later live beacon revisit | TAG_CONFIRMED_LIVE | Keep all live visits, VALID_BEACON then REPEAT_BEACON per station |
| Valid LIVE beacon alone | LIVE_ONLY | Keep the live beacon |
| Valid TAG beacon without LIVE | TAG_ONLY_RECOVERED | Recover beacon; recovered-controls count unchanged |
| Conflicting valid beacon times | CONFLICT | Keep live visits provisionally, preserve tag provenance, open review |
| FoxCore transport retry | SOURCE_DUPLICATE | Retain source fact; no additional accepted visit |

Beacon time conflicts use the same conservative discrepancy policy as CONTROL,
not the timing-withholding policy for START/FINISH. Other existing invalidity and
review rules still apply. BEACON cannot set start/finish/elapsed time or increase
distinct controls. Missing beacon evidence does not invalidate a result, generate
a missing-beacon review or prevent COMPLETE readout status. Future rule profiles
may require beacon presence using this role; no new championship/course engine
or mandatory-beacon profile is introduced here. Multiple BEACON stations remain
possible; the compact presence indicator means at least one accepted beacon.

The finish desk shows controls found, beacon and finish separately. Participant
history and review pages localize beacon labels; the public display stays simple.
Recalculation/restart with identical evidence remains deterministic, including
beacon repeats. Historical CONTROL/START/FINISH scoring remains unchanged.

## Validation boundary

Parser/unit, simulator/import, browser and software-level recovery tests are
separate from physical reader acceptance. No new firmware/provider hardware
validation is claimed. The M3 Windows physical acceptance checklist remains
pending independently of M5 software acceptance.
