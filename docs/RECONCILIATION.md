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
* Conflicting valid CONTROL times keep the live history provisionally; station
  presence is not lost, but a review is open. No conflicting tag time silently
  replaces the live visit. For START/FINISH conflicting times are withheld from
  resolved timing until a reasoned choice; original observations remain visible.
* Wrong event, unknown event ID, malformed/failed file, nonzero reserved byte,
  unknown sync byte, unsynchronized time, invalid/pre-sync time, outside window
  and unknown/disabled station are retained, not automatically counted.
* LIVE duplicate/exclusion/invalidity classification remains unchanged. Valid
  tag evidence can recover a station despite an invalid live observation, but
  does not make that original observation valid.

Resolved accepted observations use the existing earliest valid control/start and
finish-after-start logic. Readout time is never a replacement scoring timestamp.
Competition status and result completeness are independent: PROVISIONAL (no
successful readout), COMPLETE (review-free readout), REVIEW_REQUIRED (open case).
Completeness does not alter sporting ranks; unresolved timing cannot fabricate
an elapsed time. Public displays expose only a concise provisional indicator.

## Adjudication and provenance

An operator may choose a specific live/tag record, exclude a station, accept
CONTROL presence without trusting time, add a manual whole-second observation,
or override timing with MANUAL evidence. Every action requires a reason and
records operator, before/after and timestamp in audit. Source timestamps are
never edited. CONTROL presence acceptance is an explicit exception to automatic
chronological timing checks and counts that station once; it cannot define
START/FINISH or elapsed time.

Decisions append, never replace/delete. AUTO supersedes a ruling and restores
automatic review. A decision references the evidence fingerprint it reviewed;
new/different evidence reopens review instead of silently inheriting an old
ruling. DNS/DNF/DSQ use the existing audited EventEntry status workflow.

Each resolved observation references its LIVE punch, TAG record or MANUAL
decision. Participant detail and evidence export retain all observations,
including superseded snapshots. Ordinary result export adds completeness,
recovered-control count, review and manual indicators, not raw bytes.

Closing with open cases needs explicit confirmation. Closing does not destroy
or permanently freeze evidence; archive remains read-only. Recalculation/restart
rebuild derived state from associations, source facts and latest applicable
decisions without publishing old snapshots as newly arrived readouts.

## Validation boundary

Parser/unit, simulator/import, browser and software-level recovery tests are
separate from physical reader acceptance. No new firmware/provider hardware
validation is claimed. The M3 Windows physical acceptance checklist remains
pending independently of M5 software acceptance.
