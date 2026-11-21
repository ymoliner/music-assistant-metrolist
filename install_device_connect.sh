#!/usr/bin/env bash
set -euo pipefail

repo="ymoliner/music-assistant-metrolist"
ref="${METROLIST_DEVICE_CONNECT_REF:-main}"
container="${1:-}"
provider_source=""
if [[ -f "$PWD/metrolist_device_connect/manifest.json" ]]; then
  provider_source="$PWD/metrolist_device_connect"
elif [[ "${0##*/}" != "bash" && -f "${0%/*}/metrolist_device_connect/manifest.json" ]]; then
  provider_source="$(cd -- "${0%/*}/metrolist_device_connect" && pwd)"
fi
tmp_dir=""

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker CLI is unavailable. Run this on the Home Assistant host with Docker access." >&2
  echo "An ordinary add-on terminal usually cannot install files into another add-on." >&2
  exit 2
fi

if [[ ! -f "$provider_source/manifest.json" ]]; then
  if ! command -v curl >/dev/null 2>&1; then
    echo "curl is required to download the provider from GitHub." >&2
    exit 2
  fi
  tmp_dir="$(mktemp -d)"
  trap 'find "$tmp_dir" -type f -delete; rmdir "$tmp_dir" 2>/dev/null || true' EXIT
  provider_source="$tmp_dir/metrolist_device_connect"
  mkdir -p "$provider_source"
  for file in __init__.py account.py session.py player.py setup_flow.py manifest.json VERSION; do
    curl --fail --silent --show-error --location \
      "https://raw.githubusercontent.com/$repo/$ref/metrolist_device_connect/$file" \
      --output "$provider_source/$file"
  done
fi

if [[ -z "$container" ]]; then
  mapfile -t candidates < <(
    docker ps --format '{{.Names}}' |
      while IFS= read -r name; do
        if docker exec "$name" sh -c 'test -f /data/options.json || test -n "${SUPERVISOR_TOKEN:-}"' >/dev/null 2>&1 &&
           docker exec "$name" python -c 'import music_assistant' >/dev/null 2>&1; then
          printf '%s\n' "$name"
        fi
      done
  )
  if [[ ${#candidates[@]} -ne 1 ]]; then
    echo "Expected exactly one running Home Assistant Music Assistant add-on; found ${#candidates[@]}." >&2
    echo "Usage: $0 [music-assistant-addon-container-name]" >&2
    exit 2
  fi
  container="${candidates[0]}"
fi

if ! docker inspect "$container" >/dev/null 2>&1; then
  echo "Container '$container' was not found." >&2
  exit 2
fi
if ! docker exec "$container" sh -c 'test -f /data/options.json || test -n "${SUPERVISOR_TOKEN:-}"' >/dev/null 2>&1; then
  echo "Container '$container' does not look like a Home Assistant add-on." >&2
  exit 2
fi
providers_dir="$(docker exec "$container" python -c 'from pathlib import Path; import music_assistant; print(Path(music_assistant.__file__).parent / "providers")')"
docker exec "$container" mkdir -p "$providers_dir/metrolist_device_connect"
docker cp "$provider_source/." "$container:$providers_dir/metrolist_device_connect/"
docker restart "$container" >/dev/null

printf 'Installed Metrolist Device Connect into %s and restarted the add-on.\n' "$container"
printf 'Add it under Music Assistant → Settings → Player Providers.\n'
printf 'Manual provider files are removed when the add-on container is replaced or updated.\n'
