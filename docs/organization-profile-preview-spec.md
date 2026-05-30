# Organization Profile Preview Spec

## Purpose

This spec defines future organization profile previews. It is not an active UI
or execution implementation plan. The canonical library remains stable; future
profiles generate alternate preview/export layouts from canonical metadata.

Related documents:

- [Organized Library Contract](organized-library-contract.md)
- [Original To Organized State Model](original-to-organized-state-model.md)

## Current Boundary

Active scope:

- lock organized folder contract
- preserve original source state
- plan canonical output

Out of scope now:

- dropdown UI
- profile switching
- preview rendering
- execution from a profile
- automatic file movement
- downloader changes

## Future Profiles

Future profile ids:

- `artist_release_default`
- `genre_first`
- `decade_first`
- `release_type_first`
- `energy_first`
- `review_status`
- `custom`

Profiles are view/export recipes. They do not redefine canonical metadata and
do not become the source of truth for physical ownership.

## Profile Semantics

### artist_release_default

The stable canonical layout from the organized library contract:

```text
Music/Artists/<Album Artist>/<Release Type>/[<Year>] <Album>/<Disc>-<Track> - <Track Title>.<ext>
```

### genre_first

Preview grouping starts with genre metadata. Genre remains metadata and UI
filtering first, not the default physical owner.

### decade_first

Preview grouping starts with release decade, derived from canonical release
year when available.

### release_type_first

Preview grouping starts with Albums, EPs, Singles, Live, Compilations, and
other release-type evidence.

### energy_first

Preview grouping starts with future local energy/mood metadata when available.
This profile must not invent energy values when evidence is absent.

### review_status

Preview grouping starts with clean, review, unresolved, duplicate, and unsafe
states so operators can inspect backlog and governance zones.

### custom

Future user-defined layout rules. Custom profiles must be preview-first,
validated, and reversible before any execution workflow is considered.

## Preview Rules

- Profiles generate preview/export layouts from canonical metadata.
- The dropdown UI comes later.
- Changing a dropdown must not immediately move files.
- Preview comes first.
- Execution requires explicit confirmation and an execution manifest.
- Canonical library layout remains stable across profile changes.
- Original relative path evidence must remain linked in `_System/`.
- Review and unresolved items must remain visibly review/unresolved; profile
  previews must not make them look cleanly organized.

## Future UI Proof Concept

Later UI proof should explain the flow:

```text
Messy Source -> System Judgment -> Organized Destination
```

Future screens:

- Library Overview
- Messy to Organized Explorer
- Folder Tree Preview
- Review Queues

These screens are future UI scope only. They are not active implementation in
the current docs-first architecture lock.

## Safety Rules

- Profile previews must be non-mutating.
- Profile changes must not modify source files.
- Profile changes must not execute placement.
- `execute-placement`, `quarantine-duplicates`, and `restore-quarantine` remain
  outside the proof phase.
- Preview exports must preserve source and canonical evidence links.

