# Public Fixture Library

This directory contains a metadata-only public validation fixture for the Music
Library Intelligence Platform.

- `external_metadata_fixture.csv` contains fictional track metadata only.
- No audio, media files, downloads, API credentials, or private paths are used.
- Generated reports are written under `reports/runs/local_fixture/public_fixture/`
  when the documented validation commands are run from the repository root.
- `expected_summary.md` lists the expected non-brittle evidence categories.

See [../../docs/public-fixture-validation.md](../../docs/public-fixture-validation.md)
for the exact command sequence.
