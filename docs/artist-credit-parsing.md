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
artist plus collaborating artists when the split is clean and no protected
group-name rule applies.

## Protected Group Names

MusicBrainz validation showed that canonical band, ensemble, orchestra, and
group names often contain the same separators used by collaborations. The
parser therefore protects deterministic group-name patterns before applying
generic `&`, `and`, or comma splitting.

Protected suffixes include forms such as `and His Orchestra`, `and Her
Orchestra`, `and Their Orchestra`, `and the Band`, `and the Banshees`, `and His
Lost Planet Airmen`, `and Company`, `& His Orchestra`, `& Her Orchestra`, `&
The Orchestra`, and `& Company`.

The rule also covers short possessive or `the` phrases that end in strong
ensemble terms such as band, choir, ensemble, or orchestra.

Examples preserved as single artist credits include:

- `Emerson, Lake & Palmer`
- `Jimmy Dorsey & His Orchestra`
- `Siouxsie and the Banshees`
- `Commander Cody and His Lost Planet Airmen`
- `Martin & Company`
- `Bob Marley and the Wailers`
- `Tom Petty and the Heartbreakers`
- `Nick Cave and the Bad Seeds`

These rows receive `protected_group_name`. Separator-only group boundaries,
such as comma plus ampersand names, also receive `possible_group_name` and
`ambiguous_separator`.

## Ambiguity Boundary

The parser preserves ambiguity instead of forcing a primary artist when a
credit looks like a collective or band name, contains source/channel/label
artifacts, contains title-like delivery/version pollution, has unreliable
punctuation, or uses unsupported separators.

Not every `&`, comma, or `and` means collaboration. Those separators can be
part of a canonical group name, so the parser only emits collaborator evidence
when the deterministic boundary checks are clean.

Ambiguous records are written to `unresolved_artist_credits.csv` with low
confidence and explanatory `parser_flags_json` values.

## Confidence

High confidence means a clean solo artist, an explicit featured marker with a
clean primary and clean featured artist names, or a protected group name with a
strong group suffix.

Medium confidence means a clean collaboration marker such as `with`, `&`, `x`,
`vs`, comma-separated credits, or a protected separator boundary that may be a
canonical group name.

Low confidence means the artist credit is ambiguous, malformed, contains likely
source artifacts, or contains title-like pollution.

## Future Integration

v1 prepares role-aware evidence for future canonical graph integration. It does
not change canonical entities, aliases, graph relationships, local library data,
or media tags.
