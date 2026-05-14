# Conflict Resolution Governance

Conflict Resolution Governance v1 is a review-only layer for unresolved
canonical graph conflicts. It makes conflict state explainable without
collapsing identities or reducing `unresolved_conflicts` unless a conflict is
actually resolved by a later reviewed workflow.

## Why Conflicts Are Preserved

Canonical graph conflicts often mean two plausible interpretations exist at the
same time: an alias may be only a casing variant, a track title may appear where
an artist should be, an uploader artifact may look like a label or artist, or a
collaboration string may not represent a single artist identity.

The governance layer preserves those conflicts because silent collapse can
damage the graph. It produces a deterministic conflict record with source and
target entities, role, status, severity, confidence snapshot, positive and
negative evidence, contradiction reason, and recommended action.

## Merge Veto Logic

Governance blocks unsafe merge candidates when any deterministic veto is true:

- Roles conflict and no approved review decision exists.
- Either side has dominant artifact evidence.
- A collaboration string conflicts with a single artist identity.
- Lifecycle state is `conflicted`, `blocked`, or `deprecated`.
- The confidence gap is too small to determine a canonical winner.

Blocked rows are written to:

```text
reports/conflict_governance/blocked_merges.csv
```

## Safe Merge Candidate Logic

`safe_to_merge_candidate` is only a review label. It does not execute a merge.

A conflict can enter that bucket only when all of these are true:

- The entities have the same role.
- Alias evidence is strong.
- Negative evidence is low.
- Approved review evidence or normalization knowledge exists.
- Artifact flags do not dominate.
- Lifecycle state is `probationary` or `canonical`.

Rows are written to:

```text
reports/conflict_governance/safe_merge_candidates.csv
```

## Review-First Governance

Run governance with:

```bash
python -m app.main conflict-governance --out reports
```

It writes:

```text
reports/conflict_governance/
  conflict_summary.json
  conflicts.csv
  blocked_merges.csv
  safe_merge_candidates.csv
  needs_review.csv
```

The review UI exposes the report at `/review/conflicts`, including blocked
merges, safe merge candidates, needs-review rows, severity badges, recommended
actions, rationale, and evidence snippets.

The canonical graph summary references governance counts when the governance
report is available:

- `governed_conflicts`
- `blocked_merges`
- `safe_merge_candidates`
- `needs_review_conflicts`

## No Mutation Boundary

Conflict governance is observational. It may read SQLite observations,
canonical graph output, confidence evidence, review decisions, and normalization
knowledge. It may write governance report files.

It must never:

- Mutate media files.
- Write metadata tags.
- Move, rename, delete, or copy source media.
- Auto-merge conflicted entities.
- Add AI APIs, embeddings, or vector databases.
- Remove lifecycle or confidence protections.
