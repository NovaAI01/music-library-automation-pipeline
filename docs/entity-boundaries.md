# Entity Boundary Classifier

Entity Boundary Classifier v1 is a deterministic pre-governance sanitation
layer. It classifies raw metadata candidate strings before role assignment and
canonical graph insertion, so polluted artist or album candidates do not create
avoidable role-collision conflicts downstream.

The classifier runs in this pipeline position:

```text
raw metadata
-> normalization
-> entity boundary classification
-> role assignment
-> alias equivalence
-> conflict governance
-> canonical graph
```

## Boundary Decisions

Each boundary row records the candidate value, source field, proposed boundary
type, confidence score, status, flags, and rationale. Statuses are:

- `allow`: proceed to the existing classifier, confidence, lifecycle, and graph flow.
- `block`: do not promote into canonical artists or albums.
- `quarantine`: keep as reviewable boundary evidence, not canonical evidence.
- `needs_review`: keep reviewable, but do not promote automatically.

Blocked, quarantined, and needs-review boundaries can still appear as
unresolved evidence. They are not merged, promoted, or written to media files.

## Detection Scope

The classifier blocks or quarantines deterministic pollution patterns:

- Official audio, video, music video, and lyric video markers in artist or album candidates.
- Remaster, version, explicit, clean, radio edit, and edit markers in artist or album candidates.
- Uploader, channel, platform, source, studio, record label, and label residue.
- Comma-separated or `ft` / `feat` / `featuring` collaboration strings.
- `band` suffix source names when the folder artist disagrees.
- Bracket-only release annotations.
- Title-like strings in artist fields when title or folder context supports pollution.

It preserves valid entities such as casing aliases (`Tool` and `TOOL`), artist
names (`System of a Down`, `Alice in Chains`), and real album titles such as
`Badmotorfinger`, `L.D. 50`, `Dark Sun`, and `Dear Agony` when album evidence
supports the album role.

## Reports

Run:

```bash
python -m app.main entity-boundaries --out reports
```

It writes:

```text
reports/entity_boundaries/
  entity_boundary_summary.json
  entity_boundaries.csv
  blocked_boundaries.csv
  quarantined_boundaries.csv
  needs_review_boundaries.csv
```

Summary metrics include allowed, blocked, quarantined, and needs-review
candidate counts, plus source artifact, collaboration, title pollution, and
release annotation counts.

## Relationship To Governance

Boundary classification differs from alias equivalence and conflict governance:

- Boundary classification prevents polluted candidates from becoming canonical
  artist or album evidence too early.
- Alias equivalence only labels safe casing and punctuation aliases after the
  boundary and role checks.
- Conflict governance remains the final review-only classifier for unresolved
  graph conflicts.

All three layers are observational. They do not mutate media files, write
metadata, call external APIs, use embeddings, or auto-merge entities.
