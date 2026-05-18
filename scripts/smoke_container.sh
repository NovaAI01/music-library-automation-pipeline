#!/usr/bin/env bash
set -euo pipefail

IMAGE_NAME="music-library-intelligence:local"
CONTAINER_NAME="music-library-smoke-test"
PORT="${PORT:-8000}"
HEALTH_URL="http://127.0.0.1:${PORT}/health"

cleanup() {
    docker rm -f "${CONTAINER_NAME}" >/dev/null 2>&1 || true
}

trap cleanup EXIT

docker build -t "${IMAGE_NAME}" .
docker rm -f "${CONTAINER_NAME}" >/dev/null 2>&1 || true
docker run -d --name "${CONTAINER_NAME}" -p "${PORT}:8000" "${IMAGE_NAME}" >/dev/null

deadline=$((SECONDS + 60))
health_status=""

while [ "${SECONDS}" -lt "${deadline}" ]; do
    health_status="$(docker inspect --format '{{.State.Health.Status}}' "${CONTAINER_NAME}")"
    if [ "${health_status}" = "healthy" ]; then
        break
    fi
    if [ "${health_status}" = "unhealthy" ]; then
        break
    fi
    sleep 2
done

docker inspect --format '{{json .State.Health}}' "${CONTAINER_NAME}"

if [ "${health_status}" != "healthy" ]; then
    echo "Container did not become healthy within 60 seconds; status: ${health_status}" >&2
    exit 1
fi

python - "${HEALTH_URL}" <<'PY'
import sys
import urllib.request

url = sys.argv[1]
with urllib.request.urlopen(url, timeout=5) as response:
    body = response.read()
    if response.status != 200:
        raise SystemExit(f"Unexpected status from {url}: {response.status}")
    print(body.decode("utf-8"))
PY

echo "Container smoke test succeeded for ${IMAGE_NAME} at ${HEALTH_URL}"
