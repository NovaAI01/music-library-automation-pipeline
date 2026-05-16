# Album Cohesion Engine

Album Cohesion Engine v1 is a read-only inference and reporting layer. It
groups likely album members from repeated local evidence and writes review
artifacts under `reports/album_cohesion/`.

Run:

```bash
python -m app.main album-cohesion --out reports
```

By default the command reads `reports/library_qa/file_health.csv`. It can also
scan a library root directly with `--library-root`.

## Evidence Sources

The engine uses local evidence only:

- artist values from tags, filenames, and placement
- album tags
- track numbers
- year/date tags
- source folder and directory structure
- filename album and title patterns
- repeated track co-occurrence in the same inferred group
- organized placement structure from existing paths
- metadata suggestion source evidence, including normalization knowledge and
  album cohesion references when those reports already exist

No external API, embedding store, fingerprinting service, or network lookup is
used in v1.

## Scoring

Each group receives:

- `cohesion_score`, from `0.0` to `1.0`
- `confidence_tier`: `high`, `medium`, or `low`
- `rationale`: short evidence statements for review

Positive signals include repeated album folder structure, consistent repeated
album tags, sequential track numbering, shared release year, repeated
co-occurrence, consistent artist normalization, and filename similarity.

Negative signals include conflicting album tags and probable compilation mixes.
The score is intentionally cumulative: a single field can suggest a group, but
high confidence requires multiple evidence patterns to agree.

## Group Behavior

The report classifies inferred groups as:

- `album`: repeated evidence supports a likely album grouping
- `single`: only one track has album-like evidence
- `compilation_mix`: multiple artist identities suggest a mixed release
- `conflict`: album evidence disagrees inside a likely group

Tracks without enough album evidence are written to `orphan_tracks.csv`.

## Conflict Handling

Conflicts are reported, not resolved. The engine writes
`album_conflicts.csv` when a likely group contains conflicting album tags or a
folder contains multiple album tag values. These rows are intended for human
review before any future metadata or placement workflow.

## Safety Boundaries

The engine does not:

- write or remove metadata tags
- move, copy, rename, or delete media files
- create album folders
- auto-approve album assignments
- replace existing album organization or album discovery logic
- call external services

Metadata suggestions may include album cohesion evidence in rationale/source
evidence, but suggested album values still require human review and are never
auto-applied.
