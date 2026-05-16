# Canonical Entity Graph

Canonical Entity Graph v1 turns local observations and review history into a
persistent, evidence-governed entity resolution layer. It is inferential only:
it writes canonical graph tables and reports, but never mutates media files,
metadata tags, or library placement.

## Entity Model

The graph persists four canonical entity tables:

- `canonical_artists`
- `canonical_albums`
- `canonical_tracks`
- `canonical_versions`

Each entity has:

- `canonical_id`
- `canonical_name`
- `confidence_score`
- `confidence_tier`
- `evidence_count`
- `conflict_count`
- `first_seen`
- `last_seen`
- `status`

IDs are deterministic hashes of entity type and normalized evidence key, so
reruns update a stable graph snapshot rather than creating new identities for
the same accumulated evidence.

## Relationship Model

Relationships are stored in `entity_relationships` with:

- `relationship_id`
- `source_entity`
- `target_entity`
- `relationship_type`
- `confidence_score`
- `supporting_evidence_count`
- `conflicting_evidence_count`
- `rationale`
- `created_at`

Supported relationship types:

- `alias_of`
- `belongs_to_album`
- `probable_duplicate`
- `probable_live_version`
- `probable_remaster`
- `probable_single`
- `probable_compilation_member`
- `probable_same_track`

Relationship rationale is intentionally short and review-facing. It explains
the evidence class that produced the edge, such as approved alias knowledge,
album cohesion, repeated normalized title co-occurrence, or version markers.

## Evidence Flow

The graph reads local evidence from:

- SQLite file, tag, filename, and identity observations.
- Metadata review decisions.
- Normalization knowledge derived from approved and rejected decisions.
- Album cohesion reports.
- Evidence reliability reports.
- Folder and filename normalization evidence.
- Repeated co-occurrence of artist, album, and title values.
- Artist casing approvals.

The graph command is:

```bash
python -m app.main canonical-graph --out reports
```

It writes:

```text
reports/canonical_graph/
  canonical_artists.csv
  canonical_albums.csv
  canonical_tracks.csv
  canonical_versions.csv
  entity_relationships.csv
  unresolved_conflicts.csv
  graph_summary.json
```

## Confidence Evolution

Confidence increases when evidence repeats, prior review approvals agree,
normalization knowledge maps a noisy value to a target value, album cohesion
supports track membership, and reliability scoring indicates low pollution.

Confidence decreases when conflicts appear, evidence is low reliability,
uploader or channel pollution is present, or a value has only one weak source.

Confidence tiers are:

- `high`
- `medium`
- `low`

The tier is a review signal, not permission to mutate files.

## Conflict Handling

Conflicts are stored in `canonical_unresolved_conflicts` and exported as
`unresolved_conflicts.csv`. Typical conflicts include casing variants without an
approved alias, album tag disagreement in the same inferred group, and alternate
track version markers that prevent a clean collapse.

The graph never auto-collapses conflicting entities without supporting review
or repeated evidence. Conflicted entities remain visible with `status` set to
`conflicted` and non-zero `conflict_count`.

## Operational Boundaries

The graph is:

- Observational.
- Inferential.
- Evidence-governed.
- Review-oriented.

The graph must never:

- Write or rewrite media metadata.
- Move, delete, copy, or rename media files.
- Auto-apply metadata suggestions.
- Discard conflicting evidence.
- Call external APIs.
- Use LLM calls, embeddings, or vector databases.

The UI page at `/review/canonical-graph` exposes canonical entities,
relationships, aliases, unresolved conflicts, confidence tiers, evidence
counts, and rationale snippets for review.
