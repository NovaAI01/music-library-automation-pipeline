# Music Library Intelligence Platform — Portfolio Brief

## Project

Music Library Intelligence Platform

## One-line summary

A local-first metadata intelligence platform that turns messy music-library data into evidence-backed, human-reviewed cleanup planning without downloading audio, mutating the local library, or relying on AI/LLM enrichment.

## Problem

Music libraries accumulate inconsistent artist names, missing album context, duplicate-looking records, release variants, compilation tracks, source artifacts, and uncertain metadata. Direct automation is risky because a duplicate-looking track may be a legitimate release appearance, and a confident-looking metadata value may still be polluted by source or uploader context.

## Solution

The platform treats library cleanup as a governed data-quality workflow. It separates ingestion, evidence extraction, identity analysis, conflict classification, confidence scoring, validation benchmarking, review decisions, and quarantine/restore boundaries.

The result is not automatic cleanup. It is a reviewable evidence system that helps a human decide what is safe, blocked, or deferred.

## What the system does

- Scans local metadata and records evidence in a local workflow.
- Converts external source metadata into a common validation contract.
- Parses artist credits and separates primary, featured, collaboration, and unresolved cases.
- Detects duplicate-like records and explains many through release identity analysis.
- Groups validation issues into benchmark cohorts and conflicts.
- Separates safe merge candidates, blocked merges, and deferred conflicts for review.
- Preserves auditability through reports, manifests, and review boundaries.

## Safety boundaries

The platform is designed around explicit non-destructive boundaries:

- not a downloader
- not a streaming replacement
- not an AI wrapper
- not an automatic tag writer
- no unsafe automatic mutation

For the public fixture, the manifest records:

- `metadata_only=true`
- `audio_downloaded=false`
- `local_library_mutated=false`
- `canonical_graph_mutated=false`

For Jamendo validation, audio/media URLs are redacted and `audio_download_allowed=false`.

## Architecture

```text
local or external metadata
  -> ingestion / conversion
  -> normalized external track contract
  -> evidence validation
  -> artist-credit parsing
  -> release identity analysis
  -> benchmark cohort classification
  -> conflict governance
  -> reviewable reports and manifests
```

Local library workflows remain separated from external validation inputs. External validation can produce benchmark evidence without mutating local files or the canonical graph.

## Evidence

### Public fixture

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

### MusicBrainz 50k

- 50,000 tracks seen
- 49,773 accepted after conversion
- 227 rejected
- 49,773 records ingested
- 0 ingestion rejects
- 0 missing artist / album / title fields
- 49,407 artist credits parsed
- 13,712 duplicate-like records explained by release identity analysis
- benchmark completed in 2.45s

### Jamendo 10k

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

## Engineering decisions

- Deterministic first: metadata cleanup needs traceable reasoning and repeatable reports.
- Review over automation: uncertain changes are surfaced as safe, blocked, or deferred instead of executed automatically.
- Release-aware duplicate analysis: duplicate-looking records are interpreted in release context before being treated as cleanup candidates.
- Isolated validation: external metadata benchmarking is kept separate from local library mutation and canonical graph mutation.
- Evidence-led positioning: public documentation distinguishes validated sources from deferred or unvalidated sources.

## What this demonstrates

- governed systems engineering
- data validation and normalization
- automation with safety boundaries
- confidence and conflict modeling
- reproducible evidence generation
- human-in-the-loop operational design
- technical communication for portfolio, interview, and CV use

## What this does not claim

The project does not claim:

- all sources are validated
- automatic remediation
- AI/LLM functionality
- audio downloading
- streaming replacement behavior
- automatic tag writing
- unsafe automatic mutation

Discogs, Internet Archive live validation, and YouTube metadata remain unvalidated or deferred.

## Strongest project positioning

A governed metadata intelligence and validation platform that converts messy music-library evidence into safe, reviewable remediation planning with reproducible public evidence and clearly stated operational boundaries.
