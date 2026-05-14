# Canonical Entity Classification

Canonical Entity Type Classifier v1 is a deterministic guardrail between raw
metadata evidence and the persistent Canonical Entity Graph. It exists because
messy local libraries often contain artist fields that are really track titles,
uploader names, label channels, vault names, platform residue, or version
descriptors.

The classifier runs before graph promotion and assigns each candidate one of:

- `canonical_artist`
- `canonical_album`
- `canonical_track`
- `version_descriptor`
- `source_or_label_artifact`
- `uploader_channel_artifact`
- `track_title_misclassified_as_artist`
- `album_title_misclassified_as_artist`
- `unknown_or_ambiguous`

Each classification includes the original candidate value, proposed entity
type, score, confidence tier, flags, and rationale.

## Inputs

The classifier accepts candidate values with local context:

- source field name
- file path
- folder artist
- filename artist and title parse
- observed metadata tags
- evidence reliability flags
- album cohesion context
- normalization knowledge support
- review decision support

No external APIs, embeddings, vector databases, or LLM calls are used.

## Pollution Prevention

The highest-risk case is a track title promoted as a canonical artist. The
classifier blocks that when an artist candidate matches filename or tag title
context, contains official/remaster/version suffixes, appears as a title in
other records, has a track-like phrase shape, appears only once as artist
evidence, or disagrees strongly with the folder artist.

Uploader and source artifacts are also blocked when candidates look like
channel names, label/vault/channel forms, official brand names, uploader-style
handles, platform residue, or values ending in `band` while the folder artist
disagrees.

Valid artist confidence increases when a value matches folder artist context,
repeats across tracks, has approved review decision support, has normalization
knowledge support, appears consistently as artist metadata, and has a low
conflict rate.

## Reports

Run:

```bash
python -m app.main classify-canonical-entities --out reports
```

Output:

```text
reports/canonical_entity_classification/
  entity_classification_summary.json
  entity_classifications.csv
  blocked_entity_candidates.csv
  ambiguous_entity_candidates.csv
```

Summary metrics include total candidates, canonical artist/album/track
candidates, blocked candidates, ambiguous candidates, source artifacts, and
misclassified track titles.

## Graph Relationship

The Canonical Entity Graph uses the same classifier before creating persistent
artists and albums. Blocked candidates are not promoted as active canonical
entities. Ambiguous candidates are retained as unresolved conflicts with the
classification rationale, so reviewers can inspect why promotion was withheld.

Tracks still remain observable through track evidence and version records where
appropriate; the classifier only prevents polluted candidate strings from
becoming the wrong canonical entity type.

## No Mutation Boundary

Classification is read-only. It does not write metadata, mutate music files,
move files, delete files, or approve review decisions. It only reads local
ledger evidence and report context, then writes review reports.
