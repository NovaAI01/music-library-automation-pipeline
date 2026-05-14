# Canonical Confidence

Weighted Canonical Confidence v1 replaces brittle one-off confidence heuristics
with deterministic evidence accumulation.

Each entity collects positive and negative evidence. The raw confidence signal
is:

```text
raw_confidence = positive_evidence_total - negative_evidence_total
```

The raw value is normalized into `0.0..1.0` with a deterministic logistic
normalizer. Confidence tiers are then assigned as `high`, `medium`, `low`, or
`blocked`. A blocked tier requires dominant negative evidence; weak artifact
signals alone do not override strong repeated canonical evidence.

Calibration Refinement v1 dampens repeated evidence from the same family before
normalization. High confidence requires more than repeated metadata alone, so
versioned track titles such as remasters can remain canonical-track evidence
while staying medium confidence until folder, review, album-cohesion,
reliability, or lifecycle-history evidence also supports them.

Positive evidence includes repeated artist, album, or track metadata, folder
agreement, canonical graph reinforcement, approved normalization rules, repeated
album cohesion, stable temporal presence, and canonical role agreement.

Negative evidence includes uploader signatures, source artifact patterns,
isolated occurrence, conflicting role patterns, conflicting graph
relationships, title-like artist-field structure, excessive symbol noise,
all-caps anomalies, and weak album cohesion.

Generate the report with:

```text
python -m app.main canonical-confidence --out reports
```

Outputs:

```text
reports/canonical_confidence/
  confidence_summary.json
  scored_entities.csv
  high_confidence_entities.csv
  blocked_entities.csv
  confidence_breakdowns.json
reports/calibration/
  calibration_summary.json
```

Every scored entity exposes positive evidence, negative evidence, weighted
breakdowns, raw positive and negative totals, normalized confidence, tier, and
rationale. The classifier and canonical graph use the same deterministic
scoring primitives so role agreement, repeated folder consistency, temporal
stability, and graph reinforcement can balance weak negative signals.

The engine has no AI dependency. It does not use external APIs, embeddings, or
vector databases, and it never mutates media files or writes metadata.
