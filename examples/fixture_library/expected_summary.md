# Expected Public Fixture Summary

The public fixture is intentionally small and deterministic, but the committed
expectations stay category-based so report internals can evolve without turning
the fixture into brittle row-by-row golden output.

Expected validation evidence:

- accepted records > 0
- rejected records > 0
- metadata_only=true in `run_manifest.json`
- audio_downloaded=false in `run_manifest.json`
- local_library_mutated=false in `run_manifest.json`
- canonical_graph_mutated=false in `run_manifest.json`
- artist credit analysis used by `benchmark-validation`
- release identity analysis used by `benchmark-validation`
- safe merge candidates appear for casing and punctuation variants
- deferred cohorts appear for collaboration, edition, version, and duplicate-like evidence
- blocked cohorts appear for unresolved/source-artifact/ambiguous evidence
- possible true duplicate release identity cohorts appear
- legitimate release appearance cohorts appear
- unresolved or blocked cohorts remain visible
