# Entity Roles

Entity Role Model v1 separates a raw `entity_value` from the context where that
value appears. The same normalized text can be valid in more than one role:
artist, album, track, version, source artifact, uploader artifact, label
artifact, or ambiguous.

This prevents graph corruption caused by value-only blocking. For example,
`Audioslave`, `Flyleaf`, or `Alice in Chains` can be both an artist value and
an album value. Role-aware classification preserves those records separately
instead of globally treating the value as contaminated.

Generate the report with:

```text
python -m app.main entity-roles --out reports
```

Outputs:

```text
reports/entity_roles/
  entity_role_summary.json
  entity_roles.csv
  multi_role_entities.csv
  conflicted_roles.csv
  blocked_role_collisions.csv
```

Multi-role entities are valid when each role has contextual evidence. A role is
only conflicted when its own evidence directly contradicts local context, such
as an artist candidate matching the track title for the same file. Artifact
blocking is per role, so a source-artifact collision does not globally erase a
valid artist or album role.

The canonical classifier uses role context before artifact and cross-role
blocking. Repeated artist evidence can override weak album-title collision
evidence, and repeated album evidence can override weak source-artifact
suspicion. The canonical graph consumes the role-aware classifications and
keeps ambiguous role records as unresolved conflicts for review.

The boundary is unchanged: entity-role reports are review-only. They read local
ledger evidence and write report files only. They do not mutate media files,
write metadata, call external APIs, use embeddings, or use LLMs.
