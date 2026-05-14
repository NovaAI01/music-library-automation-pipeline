# Promotion Lifecycle

Promotion Lifecycle v1 separates canonical promotion from confidence tier. A
confidence score is evidence; lifecycle state decides how strongly an entity can
participate in the canonical graph.

Lifecycle states:

- `candidate`: newly observed or insufficient evidence.
- `probationary`: moderate confidence, stable evidence beginning, and low
  conflict pressure.
- `canonical`: sustained confidence with temporal persistence, graph
  reinforcement, and low conflicts.
- `conflicted`: strong positive and negative evidence coexist, relationships
  conflict, or role evidence is unstable.
- `blocked`: dominant artifact evidence or repeated severe negative evidence.
- `deprecated`: previously canonical or probationary, but confidence later
  collapsed.

Temporal stabilization uses `first_seen`, `last_seen`, and evidence persistence.
High confidence with short history remains probationary; medium confidence with
long stable history can become canonical. Sparse entities decay toward
candidate, while dominant artifact evidence blocks promotion.

Generate lifecycle reports with:

```text
python -m app.main promotion-lifecycle --out reports
```

Outputs:

```text
reports/promotion_lifecycle/
  lifecycle_summary.json
  lifecycle_entities.csv
  canonical_entities.csv
  probationary_entities.csv
  conflicted_entities.csv
  deprecated_entities.csv
```

Each lifecycle row includes the lifecycle state, reason, transition source,
confidence snapshot, temporal snapshot, and graph snapshot. The canonical graph
uses lifecycle states so canonical and probationary entities participate fully,
candidates remain weaker hypotheses, conflicted entities produce unresolved
warnings, blocked entities are excluded, and deprecated entities remain
historical evidence rather than disappearing silently.

The engine is deterministic and reversible. It uses local report and ledger
evidence only. It does not use AI APIs, embeddings, vector databases, external
lookups, metadata writes, or media-file mutation.
