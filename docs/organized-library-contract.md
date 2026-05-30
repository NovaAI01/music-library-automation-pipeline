# Organized Library Contract

## Purpose

This contract locks the target organization model before further
implementation. It defines what must be preserved from the original source,
what the stable canonical organized library looks like, and what remains future
preview/profile work.

Current proof library:

```text
~/Music/ScarletteTrackLibrary
```

Deprecated proof path:

```text
~/Music/ScarletteTestLibrary
```

Proof phases must not mutate the original source library. Do not run
`execute-placement`, `quarantine-duplicates`, or `restore-quarantine` as part
of the proof phase.

## Original Source Preservation

The original messy source state is evidence. It must be preserved for audit,
rollback, before/after UI proof, and future investigation.

Preserved source evidence includes:

- uploader folders
- messy filenames
- embedded tag metadata
- original relative path
- source URL or manifest evidence when available
- scan/probe/hash observations
- identity/classification/placement evidence derived from the original file

The source library is not the organized output. It remains the source-of-truth
for what was observed and must be recoverable through system evidence even
after any future copy-based placement workflow.

## Canonical Organized Output

There is one stable canonical physical output contract:

```text
OrganizedLibrary/
  Music/
    Artists/
      <Album Artist>/
        Albums/
          [<Year>] <Album>/
            <Disc>-<Track> - <Track Title>.<ext>
        EPs/
        Singles/
        Live/
    Compilations/
      Various Artists/
      Single Artist/
      Soundtracks/
      DJ Mixes/
  _Review/
    identity/
    classification/
    genre/
    placement/
    duplicates/
  _Unresolved/
    unknown/
    unsupported/
    unsafe/
  _System/
    manifests/
    reports/
    logs/
    original-path-index/
    genre-index/
```

Rules:

- `Music/` is the user-facing organized library.
- Underscore folders are system/governance zones.
- Artist/release/track is the canonical physical structure.
- Genre is metadata and UI filtering first, not the default physical owner.
- Review and unresolved items must not pretend to be cleanly organized.
- Original relative path must be preserved in system evidence.
- Canonical output paths must be generated from resolved canonical metadata,
  not from uploader/channel folder ownership.
- Physical organization must remain stable across future UI profile changes.

## Review And Unresolved Zones

Items enter `_Review/` when the system has enough evidence to explain the
problem but not enough confidence to place them cleanly.

Review queues:

- `identity/`: partial, conflicting, or unsupported identity evidence
- `classification/`: unknown or uncertain classification
- `genre/`: genre evidence requires human confirmation
- `placement/`: destination path risk, collision, or incomplete placement data
- `duplicates/`: duplicate-like groups requiring review

Items enter `_Unresolved/` when placement would be unsafe or misleading:

- `unknown/`: missing required evidence
- `unsupported/`: unsupported format or workflow boundary
- `unsafe/`: traversal, collision, or filesystem safety risk

## System Evidence

`_System/` holds operational evidence, not user music:

- `manifests/`: run manifests, source manifests, and execution manifests
- `reports/`: report snapshots relevant to organized output decisions
- `logs/`: operational logs for reviewed actions
- `original-path-index/`: mapping from canonical row/file id to original
  relative path and source path
- `genre-index/`: metadata/filter index for genre browsing without making
  genre the primary physical owner

## Current Implementation Boundary

Active scope:

- lock this organized folder contract
- preserve original source state
- plan canonical output
- document future profile previews

Current planner behavior:

- clean canonical rows produce `OrganizedLibrary/Music/...` paths
- identity review rows produce `OrganizedLibrary/_Review/identity/<original relative path>`
- classification review rows produce `OrganizedLibrary/_Review/classification/<original relative path>`
- unsplit full-album single-file sources produce `OrganizedLibrary/_Review/placement/<original relative path>`
- unresolved rows produce `OrganizedLibrary/_Unresolved/unknown/<original relative path or fallback>`
- placement planning does not execute file movement

Out of scope for the current phase:

- profile dropdown UI
- profile switching
- immediate file movement from preview changes
- placement execution
- quarantine or restore execution
- downloader changes
