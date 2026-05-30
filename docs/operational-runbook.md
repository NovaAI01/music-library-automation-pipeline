# Operational Runbook

## Purpose

This runbook documents how to run, verify, troubleshoot, and clean up the
Music Library Intelligence Platform in local and CI-oriented environments. It is
an operational reference only: it does not expand product scope, change
validation behavior, or authorize destructive workflows.

## Preconditions

- Use a Python virtual environment with project dependencies installed from the
  repository root.
- Docker must be installed and running before Docker runtime or smoke
  verification commands are used.
- Run commands from the repository root unless a command explicitly says
  otherwise.

Example Python environment setup:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## Local verification

Collect tests without executing test bodies:

```bash
python -m pytest --collect-only -q
```

This proves pytest can import and discover the configured tests, including
parametrized nodeids. It does not prove assertions pass, Docker builds, the
container starts, or the health endpoint responds.

Run the local pytest suite:

```bash
python -m pytest -q
```

This proves the collected test bodies pass in the verifying environment. It
does not prove Docker image build behavior, container runtime behavior, live
external service availability, or correctness for every private music library.

## Scarlette Track Library proof workflow

The active private proof library is:

```text
~/Music/ScarletteTrackLibrary
```

The older path `~/Music/ScarletteTestLibrary` is deprecated and should not be
used for current proof evidence.

Allowed proof-phase commands:

```bash
python -m app.main scan --source ~/Music/ScarletteTrackLibrary
python -m app.main identify --scan-run-id <ID>
python -m app.main classify --scan-run-id <ID>
python -m app.main plan-placement --scan-run-id <ID>
```

Do not run these proof-phase commands:

```text
execute-placement
quarantine-duplicates
restore-quarantine
```

The proof phase is scan/report/planning only. It must not mutate audio files,
move files into placement destinations, quarantine duplicates, or restore
quarantined files.

Current chapter-split identity expectation: numbered chapter filenames such as
`01 01. Like A Shadow.flac`, `01 My Own Summer (Shove It).flac`, and other
`NN <title>`, `NN. <title>`, or `NN NN. <title>` shapes supply track-title
evidence. Full-album parent folders supply album context. Uploader/channel
folders are treated as source context unless independently supported by known
artist evidence.

Recorded proof evidence:

| Metric | Before fix, scan 8 | After fix, scan 13 |
|---|---:|---:|
| audio files seen | 536 | 536 |
| identified | 480 | 480 |
| partial | 0 | 55 |
| conflicting | 56 | 1 |
| classified | 467 | 467 |
| uncertain | 69 | 69 |
| planned | 467 | 467 |
| blocked unknown identity | 0 | 55 |
| blocked unknown classification | 13 | 13 |
| placement conflicts | 56 | 1 |

Remaining backlog after the fix is review work, not an execution approval: 55
identity-partial rows, 13 unknown classification blocks, 69 uncertain
classifications, and 1 remaining conflict.

## Organization contract references

Use these docs before changing placement, review queue, or organization
behavior:

- [Organized library contract](organized-library-contract.md)
- [Original to organized state model](original-to-organized-state-model.md)
- [Organization profile preview spec](organization-profile-preview-spec.md)

Current scope is to preserve original source state, plan canonical output, and
keep future organization profile previews non-mutating. Do not build profile UI
or dropdown switching in the proof phase.

## Docker runtime verification

Build the local runtime image:

```bash
docker build -t music-library-intelligence:local .
```

Run the container on host port `8000`:

```bash
docker run --rm -p 8000:8000 music-library-intelligence:local
```

The container exposes the FastAPI application on container port `8000`. The
`-p 8000:8000` mapping makes it available on the local machine at
`http://127.0.0.1:8000`. Runtime health is checked through `GET /health`.

This verifies that the image can be built and the application can be started
manually. It does not prove the pytest suite passes, the smoke script cleanup
runs, or GitHub Actions succeeds.

## Smoke test

Run the container smoke script:

```bash
./scripts/smoke_container.sh
```

Use a different host port if `8000` is already in use:

```bash
PORT=8001 ./scripts/smoke_container.sh
```

The script builds `music-library-intelligence:local`, removes any stale
`music-library-smoke-test` container, starts a new temporary container, waits up
to 60 seconds for Docker health to become `healthy`, calls `/health`, prints the
health JSON, and removes the temporary container on exit.

Passing output includes Docker health evidence, the `/health` JSON response, and
a final success line similar to:

```text
Container smoke test succeeded for music-library-intelligence:local at http://127.0.0.1:8000/health
```

## Health endpoint

The health endpoint is:

```http
GET /health
```

Expected JSON:

```json
{"status":"ok","service":"music-library-intelligence-platform"}
```

The endpoint verifies that the runtime process can serve a simple local health
response. It does not validate metadata correctness, source coverage, or private
library remediation workflows.

## CI verification

Inspect recent GitHub Actions runs:

```bash
gh run list --limit 5
```

Inspect pull request checks:

```bash
gh pr checks
```

The configured CI workflow installs dependencies, runs `python -m pytest -q`,
and runs `./scripts/smoke_container.sh`. The smoke script covers local Docker
image build, temporary container startup, Docker health status, `/health`
response, and cleanup.

CI success proves the configured checks passed in GitHub Actions for the
selected branch or pull request. It does not prove private-library behavior,
live external service availability, or any manual local verification that has
not been performed.

## Troubleshooting

### Docker Permission Denied

Symptom: Docker commands fail with a permission error before the build or
container starts.

Check that Docker is running and that the current user can access the Docker
daemon. Depending on the environment, this may require starting Docker Desktop,
starting the Docker service, using the configured container runtime, or running
the verification from a terminal with Docker access.

### Port 8000 Already In Use

Symptom: `docker run` or the smoke script cannot bind host port `8000`.

Use a different host port for the smoke script:

```bash
PORT=8001 ./scripts/smoke_container.sh
```

For manual runtime verification, change only the host-side port:

```bash
docker run --rm -p 8001:8000 music-library-intelligence:local
```

Then check `http://127.0.0.1:8001/health`.

### Stale Container Name

Symptom: Docker reports that container name `music-library-smoke-test` is
already in use.

Remove the stale smoke-test container:

```bash
docker rm -f music-library-smoke-test
```

The smoke script also attempts this cleanup before starting a new temporary
container.

### Docker Build Context Unexpectedly Large

Symptom: Docker sends an unexpectedly large build context or the build is slow
before dependency installation starts.

Inspect untracked local outputs and large working data. Runtime outputs such as
reports, local data, caches, credentials, and generated databases should not be
required by the Docker build context. Large metadata dumps and working data
should live outside the repository by using `MUSIC_INTELLIGENCE_DATA_ROOT` where
applicable.

### Pytest Dependency Or Import Failure

Symptom: pytest collection or execution fails before assertions run because a
module cannot be imported.

Confirm the virtual environment is active, dependencies were installed with
`python -m pip install -r requirements.txt`, and commands are being run from the
repository root. `python -m pytest --collect-only -q` is the lowest-cost check
for import and discovery problems.

### Smoke Script Health Timeout

Symptom: the smoke script exits with a message that the container did not become
healthy within 60 seconds.

Check Docker health output printed by the script, confirm the host port is not
conflicting, and verify that Docker can run the image manually. If the container
starts but `/health` is unreachable, confirm the expected port mapping and
inspect the container logs in the local terminal.

## Cleanup commands

Remove the temporary smoke-test container if it remains after an interrupted
run:

```bash
docker rm -f music-library-smoke-test
```

Optionally prune unused Docker images after verifying that no needed local
images will be removed:

```bash
docker image prune
```

`docker image prune` can delete unused local image layers. Review the prompt
before confirming.

## Boundaries

- No audio downloads are required for local runtime, smoke, or CI verification.
- No media files are mutated by the documented operational checks.
- No external service dependency is required for the smoke script.
- No canonical graph mutation is performed by the documented operational checks.
