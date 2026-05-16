# Large-Scale Evidence Validation v1

Large-scale evidence validation analyzes already-ingested external metadata and
turns repeated problems into cohort reports. It is read-only: it does not
download audio, mutate local music files, write tags, update the local library
database, or merge anything into the canonical graph.

The command reads:

```text
$MUSIC_INTELLIGENCE_DATA_ROOT/external_metadata/{source_name}/external_tracks.csv
```

If `MUSIC_INTELLIGENCE_DATA_ROOT` is not set, the fallback is `data/`.

and writes:

```text
reports/large_scale_validation/validation_summary.json
reports/large_scale_validation/validation_cohorts.csv
reports/large_scale_validation/cohort_examples.csv
reports/large_scale_validation/high_priority_cohorts.csv
reports/large_scale_validation/source_quality_report.csv
```

Run:

```bash
python -m app.main validate-external-metadata --source local_fixture --out reports
```

## Purpose

The validation layer checks external records in aggregate before any future
canonical comparison or reviewed import work. It highlights evidence patterns
such as missing fields, duplicate records, casing variants, source artifacts,
collaboration strings, version noise, malformed dates, and malformed durations.

Artist Credit Parsing v1 follows up on the `collaboration_string` cohort by
separating primary, featured, collaborator, and unresolved artist-credit evidence
for future canonical graph integration. It is still analysis-only and does not
change canonical entities in v1.

This prevents song-by-song debugging because one report can show whether a
problem is isolated or systemic. A cohort like `source_artifact_candidate` or
`official_audio_video_noise` can represent hundreds of records that need one
reviewed rule proposal instead of hundreds of manual investigations.

## Cohorts

v1 emits cohorts for:

- `missing_artist`
- `missing_album`
- `missing_title`
- `casing_alias_candidate`
- `album_title_punctuation_variant`
- `collaboration_string`
- `source_artifact_candidate`
- `official_audio_video_noise`
- `remaster_version_noise`
- `explicit_clean_radio_edit_noise`
- `possible_track_as_artist`
- `possible_album_as_artist`
- `sparse_record`
- `duplicate_external_record`
- `malformed_duration`
- `malformed_year`

High severity cohorts identify likely source artifacts, official audio/video
pollution in artist or album fields, track or album titles appearing as artists,
and large duplicate clusters. Medium severity cohorts include collaboration
strings, remaster/version noise, punctuation variants, malformed numbers, edit
noise, and smaller duplicate groups. Low severity cohorts cover missing album
values, sparse records, and casing variants.

## Future Use

Scale validation is evidence for future rule proposals, not an importer. The
intended path remains:

```text
external metadata
  -> cohort validation
  -> canonical comparison
  -> optional reviewed import
```

Expected future sources are MusicBrainz, Discogs, Jamendo, Internet Archive,
yt-dlp metadata exports, and local fixtures. Live source adapters are still out
of scope for v1.
