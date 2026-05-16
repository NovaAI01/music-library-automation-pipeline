# Golden Entity Resolution Regression Harness

The golden harness protects canonical entity resolution behavior before adding more intelligence. It uses fixed CSV fixtures under `tests/golden_cases/` and exact pytest assertions in `tests/test_golden_entity_resolution.py`.

The fixtures cover known failure categories:

- uploader, source, and label artifacts that must stay blocked or non-canonical
- track titles that were previously misread as artists
- approved artist aliases and casing variants
- values that legitimately exist in more than one role, such as artist and album
- collaboration strings that must remain ambiguous or conflicted without explicit evidence
- remaster and version text that must not become artist or album identity
- blocked promotion examples
- similar names that must not merge without alias evidence

Each row records the expected classifier result, confidence tier, lifecycle state, blocked outcome, and any role, alias, or base-title preservation rule relevant to that case. Tests feed those rows through the existing deterministic classifier, weighted confidence scorer, lifecycle evaluator, role aggregator, and graph builder. They do not use the user's real library, mutate media files, call the network, or rely on AI APIs.

These fixtures are intentionally exact. If calibration or entity-resolution logic changes, update the golden CSV expectations in the same change as the production change and explain why the new outcome is deliberate. Do not soften the tests to accept broad outcomes unless the underlying helper only exposes a numerical score and the accepted band is part of the intended contract.

Calibration Refinement v1 deliberately moves remaster/version-title fixtures
from high/canonical to medium/probationary when the supporting signal is only
track metadata plus role agreement. The cases still classify as canonical
tracks and preserve base-title identity; the lower confidence prevents version
suffix evidence from promoting too early without additional diverse support.
