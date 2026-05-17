# Music Library Intelligence Platform — Interview Brief

## 60-second explanation

I built a local-first metadata intelligence platform for messy music libraries. The core problem is that metadata cleanup is risky: duplicate-looking tracks may be legitimate release variants, artist credits can be ambiguous, and automatic tag writing can damage a curated library.

The system ingests metadata, parses artist and release evidence, classifies conflicts, scores confidence, and produces reviewable reports. It is deliberately metadata-only for validation: it does not download audio, does not mutate the local library, does not mutate the canonical graph, and does not claim AI/LLM behavior.

I validated the approach with a public fixture, a 50k MusicBrainz metadata sample, and a 10k Jamendo metadata run. The transferable pattern is governed systems engineering: turn messy operational data into evidence, risk classes, review gates, and auditable outputs.

## 90-second interview explanation

I built the Music Library Intelligence Platform to solve a real operational problem: music libraries often contain inconsistent tags, duplicate-looking records, compilation appearances, remasters, source artifacts, and ambiguous artist credits. If a tool automatically cleans that data, it can easily collapse legitimate releases or write incorrect metadata.

My design separates the workflow into ingestion, evidence extraction, artist-credit parsing, release identity analysis, benchmark cohort classification, conflict governance, and reviewable reports. Validation runs are explicitly metadata-only and preserve safety boundaries: no audio download, no local library mutation, and no canonical graph mutation.

The evidence is concrete. The public fixture processes 65 records with 60 accepted and 5 rejected, then classifies 29 benchmark cohorts into 9 safe merge candidates, 8 blocked merges, and 12 deferred conflicts. The MusicBrainz 50k run accepted 49,773 records after conversion, parsed 49,407 artist credits, had 0 ingestion rejects, and explained 13,712 duplicate-like records through release identity analysis in a 2.45s benchmark. The Jamendo 10k run accepted 10,000 records, parsed 9,878 artist credits, created 9,945 release identity groups, and produced 205 benchmark conflicts with media/audio URLs redacted.

The project is not an AI model project. It is governed automation: deterministic validation, explicit safety boundaries, evidence-led deployment, and human review for risky decisions.

## Technical angle

The strongest technical angle is turning ambiguous operational data into a controlled evidence pipeline:

```text
metadata ingestion
  -> normalized record contract
  -> evidence validation
  -> artist-credit parsing
  -> release identity analysis
  -> cohort/conflict classification
  -> reviewable reports
```

This is relevant to deployment and customer-facing engineering because the system makes uncertainty visible, documents operating boundaries, and validates behavior with reproducible evidence instead of broad claims.

## Evidence to mention

Public fixture:

- 65 fixture records
- 60 accepted
- 5 rejected
- 29 benchmark cohorts
- 9 safe merge candidates
- 8 blocked merges
- 12 deferred conflicts
- `metadata_only=true`
- `audio_downloaded=false`
- `local_library_mutated=false`
- `canonical_graph_mutated=false`

MusicBrainz 50k:

- 50,000 tracks seen
- 49,773 accepted after conversion
- 227 rejected
- 49,773 records ingested
- 0 ingestion rejects
- 0 missing artist / album / title fields
- 49,407 artist credits parsed
- 13,712 duplicate-like records explained by release identity analysis
- benchmark completed in 2.45s

Jamendo 10k:

- 10,000 fetched
- 10,000 accepted
- 0 rejected
- 9,878 artist credits parsed
- 9,945 release identity groups
- 205 benchmark cohorts
- 205 benchmark conflicts
- `metadata_only=true`
- `audio_download_allowed=false`
- media/audio URLs redacted

## What this demonstrates to a technical reviewer

- Ability to convert messy domain data into a governed validation system.
- Safety-first automation with explicit mutation boundaries.
- Evidence modeling across ingestion, parsing, release identity, and conflict governance.
- Clear separation between validated behavior and deferred source coverage.
- Practical deployment judgment: bounded scope, reproducible outputs, and review gates.

## What not to overclaim

- Do not claim all sources are validated.
- Do not claim automatic remediation.
- Do not claim AI/LLM functionality.
- Do not claim the tool downloads audio or replaces streaming.
- Do not claim automatic tag writing.
- Do not claim Discogs, Internet Archive live validation, or YouTube metadata are validated.

## Best role alignment

- AI Deployment Engineer
- Forward Deployed Engineer
- Technical Success Engineer
- Solutions Engineer
- Automation Systems Engineer
- Developer Productivity / Codex Workflow Engineer

The best positioning is governed systems engineering, validation, automation, and evidence-led deployment rather than an AI model project.

## Final short pitch

I built a local-first metadata intelligence platform that turns messy music-library evidence into safe, reviewable cleanup planning. It is deterministic, metadata-only for validation, non-destructive by default, and backed by public fixture, MusicBrainz 50k, and Jamendo 10k evidence.
