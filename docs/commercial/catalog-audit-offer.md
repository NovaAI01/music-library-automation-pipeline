# Music Catalog Metadata QA Report

## Offer name

Music Catalog Metadata QA Report

## Who it is for

This offer is for catalog owners, labels, distributors, publishers, rights
administrators, collection managers, and independent teams who manage music
metadata and need a clearer view of catalog quality before committing to manual
cleanup or larger tooling.

It is aimed at teams with an existing metadata export, spreadsheet, or catalog
file who want evidence-based QA rather than another opaque cleanup promise.

## Problem it solves

Music catalogs often contain duplicate-like records, unclear release/version
relationships, inconsistent artist credits, collaboration naming variants, and
metadata records that look similar but should not be merged without review.

The report helps a catalog owner answer:

- Which records look duplicate-like?
- Which apparent duplicates may actually be different releases, versions, or
  appearances?
- Which artist credits need review because the primary, featured,
  collaboration, or unresolved roles are unclear?
- Which issues are high risk and worth reviewing first?
- What remediation work can be planned without mutating the source catalog?

## Input required

The customer provides a metadata export in one of these forms:

- CSV
- XML
- JSON
- Spreadsheet
- Catalog export

Useful fields include artist name, track title, release title, version text,
label, release date or year, identifiers, track numbers, disc numbers, duration,
and any existing internal IDs. The audit can still be scoped if some fields are
missing.

No audio files are required.

## What the customer receives

The deliverable is a reviewable metadata QA package focused on evidence and
prioritization:

- Metadata QA summary
- Duplicate-like record report
- Release/version ambiguity report
- Artist-credit issue report
- Confidence scoring for review candidates
- Risk-ranked remediation plan
- CSV/Markdown/PDF-ready findings

The report is designed to help a human reviewer decide what to inspect, defer,
or correct in their own catalog system.

## What it does not do

This is a metadata QA service, not a destructive catalog operation.

- No audio required
- No audio download
- No file mutation
- No automatic tag writing
- No scraping
- No streaming
- No destructive cleanup
- No promise that all catalog issues can be detected from the supplied metadata
- No change to the customer's source system

## Pilot offer

Run 1-2 pilot catalog audits for real catalog owners using a supplied metadata
export.

The pilot can be free or low-cost in exchange for direct feedback on whether
the findings are useful, whether the output format supports review work, and
whether the customer would pay for a repeatable version of the service.

The goal of the pilot is demand validation, not scale.

## Pricing hypothesis

These ranges are a hypothesis to validate, not fixed pricing:

- Pilot audit: free or discounted in exchange for feedback
- Small catalog audit: £49-£99
- Larger catalog audit: £149-£299

Pricing should be tested against catalog size, turnaround expectations, review
depth, privacy requirements, and the customer's perceived value of the findings.

## Delivery workflow

1. Confirm fit and boundaries with the catalog owner.
2. Receive a metadata export in CSV, XML, JSON, spreadsheet, or similar catalog
   export format.
3. Confirm the fields available and the audit scope.
4. Run metadata-only QA analysis against the supplied export.
5. Review duplicate-like records, release/version ambiguity, artist-credit
   issues, confidence scoring, and risk ranking.
6. Prepare CSV/Markdown/PDF-ready findings.
7. Send the report and walk through the highest-priority findings.
8. Ask demand validation questions and collect feedback.

## Example report sections

### 1. Catalog QA summary

- Number of records reviewed
- Fields available in the supplied export
- Records accepted for analysis
- Records excluded because required metadata was missing
- Overall risk distribution

### 2. Duplicate-like record report

- Clusters of records with similar artist, title, release, or identifier
  evidence
- Confidence score for each cluster
- Reasons the cluster was flagged
- Suggested review action

### 3. Release/version ambiguity report

- Records that may represent remasters, edits, live versions, compilations,
  alternate releases, or repeated release appearances
- Evidence that blocks a simple duplicate decision
- Review notes for release-level decisions

### 4. Artist-credit issue report

- Credits with ambiguous primary artist, featured artist, collaboration, or
  unresolved roles
- Repeated credit patterns that may need catalog policy decisions
- Examples of records that need human review

### 5. Risk-ranked remediation plan

- Highest-value review candidates
- Items that appear safe to inspect first
- Items that should be deferred because the evidence is unclear
- Suggested manual remediation sequence

### 6. Appendix

- Field mapping used for the audit
- Known limitations from the supplied export
- Definitions for confidence levels and issue types

## Acceptance criteria for a pilot

A pilot is considered useful if it produces enough evidence to decide whether
the service is worth repeating or improving.

Acceptance criteria:

- The customer can provide a metadata export without audio files.
- The report identifies duplicate-like, release/version, or artist-credit issues
  the customer recognizes as relevant.
- The customer can understand why records were flagged.
- The output is reviewable in CSV, Markdown, or PDF-ready form.
- The remediation plan helps the customer prioritize manual review work.
- The customer gives feedback on whether the report would be worth paying for.
- The pilot does not require source system mutation or destructive cleanup.

## Demand validation questions

Use the pilot to answer these questions:

- Is this a painful enough problem for catalog owners to discuss?
- Do catalog owners have usable metadata exports they are willing to share?
- Which finding type is most valuable: duplicate-like records,
  release/version ambiguity, artist-credit issues, confidence scoring, or
  remediation planning?
- Does the customer trust a report that explains evidence and uncertainty?
- What output format fits their workflow best?
- What turnaround time do they expect?
- Would they pay for a one-off audit?
- Would they pay again after receiving the first report?
- What catalog size or complexity changes the perceived value?
- What privacy or data-handling requirements would block purchase?
- What would make the offer clear enough to say yes without a long sales call?
