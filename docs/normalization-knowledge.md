# Normalization Knowledge

The normalization knowledge engine converts human review decisions into reusable
evidence for future metadata suggestions. It is a review-first layer: it can
change suggestion confidence and rationale, but it does not write tags, move
files, delete files, or approve future changes automatically.

## Evidence Ledger

Metadata suggestion generation starts from local evidence:

- metadata plan rows
- metadata audit rows
- filename and folder-derived evidence already captured by earlier reports

This evidence remains observational. It identifies possible cleanups such as
artist casing, title cleanup, album artist defaults, separator cleanup, and junk
suffix cleanup.

## Decision Ledger

Human review decisions are stored in the SQLite `review_decisions` ledger. Each
decision records the suggestion key, file path, field, current value, proposed
value, suggestion type, confidence, decision, reason, evidence JSON, and
timestamp.

Approved decisions are positive evidence. Rejected decisions are negative
evidence. Deferred decisions stay in the audit trail but do not become reusable
normalization rules.

## Rule Derivation

`python -m app.main build-normalization-knowledge --out reports` derives rules
from approved and rejected decision records. Rules are grouped by normalized rule
type, source value, and target value.

Derived rule types are:

- `artist_alias`
- `title_cleanup`
- `album_artist_default`
- `junk_suffix_cleanup`
- `separator_cleanup`
- `rejected_pattern`

Each rule includes counts, confidence, first and last seen timestamps, and
example decision records in `examples_json`.

## Confidence Scoring

Confidence is count-based:

- `high`: at least 3 approvals and 0 rejections
- `medium`: at least 1 approval and 0 rejections
- `low`: at least 1 approval and at least 1 rejection
- `rejected_pattern`: rejections outnumber approvals

Rejected patterns are preserved so future workflows can explain why a cleanup
should remain cautious.

## Review-First Safety Model

Knowledge can influence future metadata suggestions by adding
`normalization_knowledge:<rule_key>` to source evidence, mentioning prior
approved decision evidence in the rationale, and increasing confidence by one
tier up to `high`.

Knowledge does not auto-apply rules. Every influenced suggestion still requires
human review, and no metadata mutation path is introduced by this engine.
