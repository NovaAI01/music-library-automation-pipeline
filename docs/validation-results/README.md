# Validation Results

- [MusicBrainz 50k validation result](musicbrainz-50k-validation.md)
- [MusicBrainz 50k consolidated result](musicbrainz-50k-consolidated-result.md)

Committed validation result docs should cite artifacts from isolated report
runs, for example:

```text
reports/runs/musicbrainz/musicbrainz_50k/
```

Each labeled run contains command-specific report directories plus
`run_manifest.json`. This prevents later smoke tests or fixture runs from
overwriting benchmark evidence under legacy paths such as
`reports/validation_benchmark/`.
