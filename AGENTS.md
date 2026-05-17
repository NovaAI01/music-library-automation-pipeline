# Repository execution rules

- Do not run the full test suite in Codex if it hangs or runs longer than 60 seconds.
- Prefer focused tests inside Codex.
- For documentation-only changes, inspect the diff and leave full-suite verification to the user terminal.
- Never commit with an incomplete verification claim.
- If full pytest is required, ask the user to run `python -m pytest -q` outside Codex.
- Do not modify product scope, validation logic, source adapters, or canonical graph behavior unless explicitly requested.
