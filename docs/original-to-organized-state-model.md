# Original To Organized State Model

## Purpose

This document defines the state model between messy source files and a future
canonical organized library. It protects original source evidence while allowing
reviewable movement toward canonical placement.

Related contract: [Organized Library Contract](organized-library-contract.md).

## Immutable Source State

Every observed file starts in an immutable source state. For the active proof
set, the source root is:

```text
~/Music/ScarletteTrackLibrary
```

The deprecated `~/Music/ScarletteTestLibrary` path is not current proof
evidence.

The source state records what was actually found:

- source root
- original relative path
- uploader/channel folders
- messy filename
- extension and file size
- content hash
- embedded tag metadata
- probe status
- source URL or manifest evidence when available

Proof phases must not edit, move, rename, quarantine, restore, or delete source
audio.

## State Flow

```text
OriginalSource
  -> ObservedEvidence
  -> IdentityState
  -> ClassificationState
  -> PlacementState
  -> ReviewOrCanonicalDestination
```

### OriginalSource

The file exists at its messy original path. This state is preserved for audit,
rollback, and before/after proof.

### ObservedEvidence

Scanner and probe evidence is captured in the ledger. This state can include
hashes, tag values, filename observations, parent folders, and source manifest
evidence. It is evidence capture only.

### IdentityState

Identity resolution assigns one of:

- `identified`
- `partial`
- `conflicting`
- `unknown`

Chapter-split full-album tracks must prefer numbered chapter filename titles
over full-album uploader/title tags. Parent folders can supply album context.
Uploader folders are source evidence, not high-confidence artist ownership,
unless independently matched to known artist evidence.

### ClassificationState

Classification assigns a genre/taxonomy status from controlled local evidence.
Uncertain or unknown classification must remain reviewable and must not be
hidden inside a clean canonical folder.

### PlacementState

Placement planning proposes a destination or a governance zone. Planning is not
execution.

Destination classes:

- canonical clean destination under `OrganizedLibrary/Music/`
- review destination under `OrganizedLibrary/_Review/`
- unresolved destination under `OrganizedLibrary/_Unresolved/`

### ReviewOrCanonicalDestination

Rows with complete, safe evidence can be proposed for canonical placement.
Rows with partial, conflicting, uncertain, unsupported, or unsafe evidence must
remain in `_Review/` or `_Unresolved/`.

## Required Evidence Links

Every planned destination must retain links to:

- original source root
- original relative path
- observed file id or equivalent run identity
- scan run id
- source manifest or URL evidence when available
- selected artist/title/album/classification evidence
- placement rationale
- review or unresolved reason when not cleanly placed

The original relative path must remain queryable through `_System/` evidence,
especially `_System/original-path-index/`.

## Scarlette Proof Evidence

Current before/after proof:

| Metric | Before fix, scan 8 | After fix, scan 13 |
|---|---:|---:|
| audio files seen | 536 | 536 |
| identified | 480 | 480 |
| partial | 0 | 55 |
| conflicting | 56 | 1 |
| classified | 467 | 467 |
| uncertain | 69 | 69 |
| planned | 467 | 467 |
| blocked unknown identity | 0 | 55 |
| blocked unknown classification | 13 | 13 |
| placement conflicts | 56 | 1 |

The remaining backlog is explicit review work: 55 identity-partial rows, 13
unknown classification blocks, 69 uncertain classifications, and 1 conflict.

## Banned Proof-Phase Commands

Do not run these during the proof phase:

```text
execute-placement
quarantine-duplicates
restore-quarantine
```

The state model allows future execution only after explicit review,
confirmation, and an execution manifest.

