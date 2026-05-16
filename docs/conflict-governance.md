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
The merge still has to happen through the reviewed canonical alias workflow.

A conflict can enter that bucket only when all of these are true:

- The entities have the same role.
- Alias evidence is strong.
- Negative evidence is low.
- Approved review evidence or normalization knowledge exists.
- Artifact flags do not dominate.
- Lifecycle state is `probationary` or `canonical`.

Deterministic equivalence is a narrower path for common false positive casing
and punctuation conflicts. Before governance escalates an artist
`alias_collision`, it compares both sides with an alphanumeric casefolded
normalizer. The conflict can be marked as a safe candidate only when the
normalized values match, the visible difference is casing, spacing,
apostrophes, hyphens, colons, or punctuation, repeated artist metadata is
present, confidence is medium or high, lifecycle is not blocked, and no role,
album-membership, collaboration, official-version suffix, uploader/channel, or
dominant artifact marker is present.

Album title equivalence applies only to `album_membership_conflict` rows whose
entity role is `album`. It uses a safe title normalizer that ignores spacing,
colons, apostrophes, hyphens, ellipses, and equivalent punctuation, then keeps
the same governance gates: confidence must be medium or high, lifecycle must
not be blocked, conflicted, or deprecated, and positive evidence must include
`repeated_album_metadata` or `canonical_role_agreement`. Source artifacts,
collaboration or feature markers, official audio/video markers, dominant
artifact evidence, role collisions, and `weak_album_cohesion` still prevent the
safe candidate label.

Examples that can become safe candidates when the evidence and lifecycle gates
pass include `Tool` -> `TOOL`, `Red` -> `RED`, `System of a Down` ->
`System Of A Down`, `Shallow Bay The Best Of Breaking Benjamin` ->
`Shallow Bay: The Best Of Breaking Benjamin`, and `The Strange Case of` ->
`The Strange Case of...`. Examples that must not become safe candidates include
`Heavy Is the Crown (Official Audio)`, `Tom Morello, BEARTOOTHband`, role
collisions, blocked lifecycle states, weak album cohesion, and semantic album
differences such as edition, remaster, live, acoustic, deluxe, or special
edition terms that are present on only one side.

Safe album title candidates are not automatic merges. They are written as
`safe_to_merge_candidate` rows with the action `safe album title candidate;
merge only through reviewed canonical album workflow`.

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

## Alias Equivalence Audit

The alias equivalence audit proves whether deterministic artist alias and album
title equivalence are actually reducing governance noise. It does not change
merge decisions. It replays each governed conflict through the equivalence
classifiers and records the normalized values, equivalence category,
pre-governance equivalence decision, final governance status, escalation reason,
and whether escalation was prevented. The summary includes album title
equivalence matches, prevented escalations, and missed safe album-title
equivalents when present.

Run it with:

```bash
python -m app.main alias-equivalence-audit --out reports
```

It writes:

```text
reports/alias_equivalence_audit/
  alias_equivalence_summary.json
  alias_equivalence_audit.csv
  prevented_escalations.csv
  missed_safe_aliases.csv
  remaining_escalations.csv
```

`prevented_escalations.csv` contains deterministic safe alias matches that
ended as `safe_to_merge_candidate`. `missed_safe_aliases.csv` highlights
artist `alias_collision` rows whose alphanumeric casefolded forms match and
have safe evidence, but still escalated to `needs_review` or `blocked_merge`.
`remaining_escalations.csv` preserves the conflicts that still require review
or remain blocked.

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
