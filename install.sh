#!/usr/bin/env bash
set -euo pipefail

container="${1:-}"
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
provider_source="$script_dir"

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker CLI is required. This installer works with a Docker-hosted Music Assistant server." >&2
  echo "The standard Home Assistant OS add-on does not support installing this local provider." >&2
  exit 2
fi

if [[ ! -f "$provider_source/manifest.json" ]]; then
  echo "Run this script from the extracted repository directory." >&2
  exit 2
fi

if [[ -z "$container" ]]; then
  mapfile -t candidates < <(docker ps --filter 'ancestor=ghcr.io/music-assistant/server' --format '{{.Names}}')
  if [[ ${#candidates[@]} -ne 1 ]]; then
    echo "Couldn't identify exactly one running Music Assistant Docker container." >&2
    echo "Usage: $0 <container-name>" >&2
    exit 2
  fi
  container="${candidates[0]}"
fi

if ! docker inspect "$container" >/dev/null 2>&1; then
  echo "Docker container '$container' was not found." >&2
  exit 2
fi

if docker exec "$container" sh -c 'test -f /data/options.json || test -n "${SUPERVISOR_TOKEN:-}"' >/dev/null 2>&1; then
  echo "This is a Home Assistant add-on container. Direct edits are unsupported and may be lost on update." >&2
  echo "Use the Music Assistant Marketplace community catalog after this provider is published and admitted." >&2
  exit 2
fi

providers_dir="$(docker exec "$container" python -c 'from pathlib import Path; import music_assistant; print(Path(music_assistant.__file__).parent / "providers")')"
docker exec "$container" mkdir -p "$providers_dir/metrolist_listen_together"
for file in __init__.py player.py protocol.py manifest.json; do
  docker cp "$provider_source/$file" "$container:$providers_dir/metrolist_listen_together/$file"
done
docker restart "$container" >/dev/null

echo "Installed provider in '$container' and restarted Music Assistant."
echo "Add 'Metrolist Listen Together' in Settings → Player Providers."
