# Artist Credit Parsing v1

Artist Credit Parsing v1 analyzes collaboration strings in already-ingested
external metadata. It is report-only: it does not mutate local music files,
write metadata tags, update the local library database, alter review decisions,
auto-create aliases, auto-merge artists, or write into the canonical graph.

The command reads:

```text
$MUSIC_INTELLIGENCE_DATA_ROOT/external_metadata/{source}/external_tracks.csv
```

and writes:

```text
reports/artist_credit_analysis/artist_credit_summary.json
reports/artist_credit_analysis/parsed_artist_credits.csv
reports/artist_credit_analysis/collaboration_patterns.csv
reports/artist_credit_analysis/unresolved_artist_credits.csv
reports/artist_credit_analysis/top_collaborators.csv
```

Run:

```bash
python -m app.main analyze-artist-credits --source musicbrainz --out reports
```

Use `--limit N` for smaller local verification runs.

## Deterministic Patterns

The parser recognizes these credit patterns:

- `solo_artist`
- `feat_artist`
- `ft_artist`
- `featuring_artist`
- `with_artist`
- `versus_artist`
- `x_collaboration`
- `ampersand_collaboration`
- `comma_collaboration`
- `multi_artist_credit`
- `unknown_or_ambiguous`

Explicit `feat`, `ft`, and `featuring` markers produce a primary artist plus
featured artists when both sides are clean and non-empty. Collaboration markers
such as `with`, `vs`, `versus`, `x`, `&`, `and`, and commas produce a primary
artist plus collaborating artists when the split is clean.

## Ambiguity Boundary

The parser preserves ambiguity instead of forcing a primary artist when a
credit looks like a collective or band name, contains source/channel/label
artifacts, contains title-like delivery/version pollution, has unreliable
punctuation, or uses unsupported separators.

Ambiguous records are written to `unresolved_artist_credits.csv` with low
confidence and explanatory `parser_flags_json` values.

## Confidence

High confidence means a clean solo artist or an explicit featured marker with a
clean primary and clean featured artist names.

Medium confidence means a clean collaboration marker such as `with`, `&`, `x`,
`vs`, or comma-separated credits.

Low confidence means the artist credit is ambiguous, malformed, contains likely
source artifacts, or contains title-like pollution.

## Future Integration

v1 prepares role-aware evidence for future canonical graph integration. It does
not change canonical entities, aliases, graph relationships, local library data,
or media tags.
