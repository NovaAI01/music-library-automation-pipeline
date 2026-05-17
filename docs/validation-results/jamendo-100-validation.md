# Jamendo 100 Metadata Validation Smoke

## Source And Boundary

- Source: Jamendo metadata API
- Scale: 100 records
- Audio downloaded: no
- Media downloaded: no
- Local library mutated: no
- Canonical graph mutated: no
- Credentials: `JAMENDO_CLIENT_ID` required, stored outside the repository
- Credential config: ignored via `.config/`

This smoke result records metadata-only validation. It did not download audio,
download media assets, stream tracks, mutate local library state, or write to
the canonical graph.

## Acquisition Result

| Metric | Value |
|---|---:|
| `fetched_records` | 100 |
| `accepted_records` | 100 |
| `rejected_records` | 0 |
| `metadata_only` | `true` |
| `audio_download_allowed` | `false` |
| `client_id_source` | `environment` |

## Redaction Result

Raw payload JSON redacts media, audio, and download fields before repository-safe
documentation. The redaction check passed:

| Redaction check | Result |
|---|---|
| `audiodownload` | OK |
| `prod-1.storage.jamendo.com` | OK |
| `format=mp3` | OK |
| `mp31` | OK |
| `mp32` | OK |

## Downstream Validation Result

| Stage | Metric | Value |
|---|---|---:|
| Import | `input_records` | 100 |
| Import | `accepted_records` | 100 |
| Import | `rejected_records` | 0 |
| Artist Credit Analysis | `parsed_records` | 100 |
| Artist Credit Analysis | `unresolved_count` | 0 |
| Release Identity Analysis | `total_identity_groups` | 100 |
| Release Identity Analysis | duplicate/ambiguous groups | 0 |
| Integrated Benchmark | `total_records` | 100 |
| Integrated Benchmark | `total_conflicts` | 1 |
| Integrated Benchmark | `deferred_conflicts` | 1 |
| Integrated Benchmark | `safe_merge_candidates` | 0 |
| Integrated Benchmark | `blocked_merges` | 0 |
| Manifest | `metadata_only` | `true` |
| Manifest | `audio_downloaded` | `false` |

## Interpretation

Jamendo 100 confirms that a second live metadata source path works through
metadata acquisition, import, artist-credit analysis, release-identity analysis,
and integrated validation benchmarking.

This is smoke-scale validation only. It does not prove broad Jamendo
distribution handling, long-tail catalog behavior, larger paging stability, or
general cross-source validation yet.

The next scale gate is Jamendo 1k, then Jamendo 10k if the 1k run remains
stable.
