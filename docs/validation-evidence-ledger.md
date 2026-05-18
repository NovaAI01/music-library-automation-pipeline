# Validation Evidence Ledger

This ledger records what each validation pass checks, what a passing signal
looks like, and what remains manual. It separates collection evidence from
execution evidence and does not claim CI, Docker, or smoke coverage unless that
workflow has actually run.

## `python -m pytest --collect-only -q`

Status in this Codex session: run.

What it checks:

- pytest can import and collect the repository test suite
- tests under `tests/` and `tools/portfolio_demo/tests/` are visible to the
  configured pytest discovery
- parametrized cases expand into individual nodeids

Why it passes / expected pass signal:

- command exits with status 0
- output ends with `595 tests collected`
- nodeids are saved to `/tmp/music_pytest_nodeids.txt` for inspection

What it proves:

- the current test suite is discoverable
- the 595 count is a collection count derived from pytest nodeids

What it does not prove:

- test assertions pass
- Docker builds
- the smoke script runs
- GitHub Actions passes

Boundary notes:

- collection-only imports tests but does not execute test bodies
- no audio downloads, local media mutation, or canonical graph mutation are
  expected from collection-only

## `python -m pytest -q`

Status in this Codex session: manual verification required before commit.

What it checks:

- all collected test bodies execute
- assertions across scanner, intake, identity, classification, placement,
  duplicate review, quarantine, restore, metadata, validation, canonical graph,
  UI, and portfolio demo tooling pass

Why it passes / expected pass signal:

- command exits with status 0
- terminal reports all collected tests passing, currently expected as 595 tests

What it proves:

- the regression suite passes in the user terminal environment
- the assertions described in the [test coverage map](test-coverage-map.md)
  hold for the current branch

What it does not prove:

- exhaustive correctness for all music libraries or sources
- Docker image build/runtime behavior
- live external service availability
- approved remediation execution on private data

Boundary notes:

- the suite uses temporary fixtures and mocked network paths where documented
- public validation paths preserve metadata-only, no audio downloads, no local
  media mutation, and no canonical graph mutation boundaries

## `docker build -t music-library-intelligence:local .`

Status in this Codex session: manual verification required before commit.

What it checks:

- the Docker build context is sufficient after `.dockerignore` filtering
- the Dockerfile can install dependencies and package the local FastAPI runtime

Why it passes / expected pass signal:

- Docker exits with status 0
- image `music-library-intelligence:local` is created locally

What it proves:

- the runtime image can be built on the verifying machine
- ignored local files such as caches, credentials, SQLite DBs, reports, and data
  are not required in the build context

What it does not prove:

- the container starts successfully
- `/health` responds
- Compose works
- CI verifies Docker

Boundary notes:

- no audio downloads or external metadata service calls are expected from image
  build
- Docker was not run in this Codex session

## `./scripts/smoke_container.sh`

Status in this Codex session: manual verification required before commit.

What it checks:

- local image build and container startup through the smoke script
- Docker health state becomes `healthy`
- `/health` responds from the running container
- temporary container cleanup happens on exit

Why it passes / expected pass signal:

- script exits with status 0
- output shows the image/container evidence and a successful health response

What it proves:

- the local container runtime can start and expose the health endpoint on the
  verifying machine

What it does not prove:

- full application correctness
- Compose behavior
- GitHub Actions behavior
- private library workflows

Boundary notes:

- the smoke script is runtime verification, not a metadata validation pass
- no audio downloads, local media mutation, or canonical graph mutation are
  expected
- the script was not run in this Codex session

## GitHub Actions CI on `pull_request`

Status in this Codex session: manual verification required before commit.

What it checks:

- the configured GitHub Actions workflow for pull requests
- dependency installation
- pytest suite execution with `python -m pytest -q`
- Docker image build through `scripts/smoke_container.sh`
- container boot
- Docker health status
- `/health` response
- temporary container cleanup

Why it passes / expected pass signal:

- the pull request check run completes successfully in GitHub Actions

What it proves:

- the pull request passes dependency installation, the pytest suite, and the
  container smoke checks currently configured in CI

What it does not prove:

- local private-library workflows
- live source validation

Boundary notes:

- CI verifies the container runtime only through `scripts/smoke_container.sh`
- GitHub Actions was not queried or run in this Codex session

## GitHub Actions CI on `master` push

Status in this Codex session: manual verification required before commit.

What it checks:

- the configured GitHub Actions workflow when changes reach `master`
- dependency installation
- pytest suite execution with `python -m pytest -q`
- Docker image build through `scripts/smoke_container.sh`
- container boot
- Docker health status
- `/health` response
- temporary container cleanup

Why it passes / expected pass signal:

- the `master` push workflow completes successfully in GitHub Actions

What it proves:

- the default branch passes dependency installation, the pytest suite, and the
  container smoke checks currently configured in CI after merge or push

What it does not prove:

- private library remediation correctness
- live external API behavior

Boundary notes:

- this is post-merge/push evidence, not a substitute for local focused
  verification before commit
- this Codex session did not run or inspect a GitHub Actions execution
