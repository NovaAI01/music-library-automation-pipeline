# Release-Aware Identity Analysis v1

Release-Aware Identity Analysis v1 investigates duplicate-looking external
metadata rows without treating them as removable duplicates. It is analysis and
reporting only.

The command reads:

```text
$MUSIC_INTELLIGENCE_DATA_ROOT/external_metadata/{source}/external_tracks.csv
```

and writes:

```text
reports/release_identity_analysis/release_identity_summary.json
reports/release_identity_analysis/identity_groups.csv
reports/release_identity_analysis/release_appearances.csv
reports/release_identity_analysis/possible_true_duplicates.csv
reports/release_identity_analysis/legitimate_release_appearances.csv
reports/release_identity_analysis/ambiguous_identity_groups.csv
```

Run:

```bash
python -m app.main analyze-release-identity --source musicbrainz --out reports
```

Use `--limit N` for smaller local verification runs.

## Why Duplicate Records Are Not Removable Duplicates

`duplicate_external_records` in validation benchmarking means repeated external
evidence, not a delete decision. In MusicBrainz, one recording can appear on an
original album, a reissue, a deluxe edition, a compilation, a soundtrack, a
regional release, or another format. Those rows can be valid release
appearances of the same recording.

Release-aware identity analysis separates likely true duplicate metadata rows
from legitimate recording appearances across releases before any future
duplicate-remediation logic interprets the validation count.

The validation benchmark can consume `release_identity_summary.json` and
`identity_groups.csv` when they exist for the same source. In that mode,
`benchmark-validation` treats duplicate-looking rows as release-aware evidence
where possible, while keeping possible true duplicates, ambiguous identity
groups, and unresolved duplicate-like records visible as separate benchmark
cohorts.

## MusicBrainz Recording vs Release

MusicBrainz distinguishes a recording from the releases that contain it. This
analysis uses `recording_gid` or `recording_id` from `raw_payload_json` as the
strongest identity key when available. It then compares release evidence such
as `release_gid`, `release_id`, album name, track number, source record ID, and
duration.

When MusicBrainz recording identity is missing, the analysis falls back to
normalized artist/title/duration evidence and then normalized artist/title
evidence. Weak artist/title groups with conflicting durations are marked
ambiguous rather than treated as duplicate candidates.

## Classifications

Identity groups are classified as:

- `single_record_identity`
- `legitimate_release_appearance`
- `possible_true_duplicate`
- `edition_or_reissue_cluster`
- `compilation_or_multi_release_appearance`
- `ambiguous_identity_cluster`

`legitimate_release_appearance` means the same recording appears across
different releases or album names with consistent artist/title evidence.

`possible_true_duplicate` means repeated source record IDs or identical
artist/album/title/track/duration rows appear without clear different release
evidence.

`edition_or_reissue_cluster` means the same recording appears across album
names with edition, remaster, deluxe, special edition, or reissue wording.

`compilation_or_multi_release_appearance` means the same recording appears
across compilation, collection, best-of, anthology, soundtrack, or many-release
evidence.

`ambiguous_identity_cluster` means weak identity evidence is not sufficient to
decide, commonly because normalized artist/title matches but duration or
recording evidence conflicts.

## No Mutation Boundary

`analyze-release-identity` does not mutate source datasets, local music files,
media tags, the local music database, canonical graph tables, review decision
ledgers, or duplicate quarantine behavior. It does not auto-merge tracks,
auto-delete duplicate rows, or promote MusicBrainz evidence into canonical
identity state.

The output is intended to inform future duplicate review and remediation design
without changing current product behavior.

Benchmark integration is also reporting-only. It separates duplicate-like
records into legitimate release appearances, edition/reissue clusters,
compilation or multi-release appearances, possible true duplicates, ambiguous
identity groups, and unresolved duplicate-like records. It does not auto-merge
tracks, auto-delete rows, change duplicate quarantine, or promote release
identity output into the canonical graph.
