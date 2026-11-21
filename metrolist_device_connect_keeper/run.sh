#!/usr/bin/env bash
set -u

provider_source=/local_apps/metrolist_device_connect_keeper/provider
version_file="$provider_source/VERSION"
if [[ ! -s "$version_file" ]]; then
  echo "Provider bundle is missing VERSION; rebuild this local add-on." >&2
  exit 1
fi
wanted_version="$(cat "$version_file")"
addon_container="$(python3 -c 'import json; print(json.load(open("/data/options.json")).get("addon_container", ""))' 2>/dev/null || true)"
check_interval="$(python3 -c 'import json; print(json.load(open("/data/options.json")).get("check_interval", 30))' 2>/dev/null || echo 30)"
[[ "$check_interval" =~ ^[0-9]+$ ]] || check_interval=30

while true; do
  if [[ -n "$addon_container" ]]; then
    candidates=("$addon_container")
  else
    mapfile -t candidates < <(
      docker ps --format '{{.Names}}' |
        while IFS= read -r name; do
          if docker exec "$name" sh -c 'test -f /data/options.json || test -n "${SUPERVISOR_TOKEN:-}"' >/dev/null 2>&1 &&
             docker exec "$name" python -c 'import music_assistant' >/dev/null 2>&1; then
            printf '%s\n' "$name"
          fi
        done
    )
  fi

  if [[ ${#candidates[@]} -eq 1 ]]; then
    container="${candidates[0]}"
    if docker inspect "$container" >/dev/null 2>&1 &&
       docker exec "$container" python -c 'import music_assistant' >/dev/null 2>&1; then
      providers_dir="$(docker exec "$container" python -c 'from pathlib import Path; import music_assistant; print(Path(music_assistant.__file__).parent / "providers")' 2>/dev/null || true)"
      if [[ -n "$providers_dir" ]]; then
        installed_version="$(docker exec "$container" sh -c "cat '$providers_dir/metrolist_device_connect/VERSION' 2>/dev/null" || true)"
        if [[ "$installed_version" != "$wanted_version" ]]; then
          echo "Installing Metrolist Device Connect $wanted_version into $container"
          if docker exec "$container" mkdir -p "$providers_dir/metrolist_device_connect" &&
             docker cp "$provider_source/." "$container:$providers_dir/metrolist_device_connect/" &&
             docker exec "$container" python -c 'import music_assistant.providers.metrolist_device_connect' &&
             docker restart "$container" >/dev/null; then
            echo "Installed provider and restarted $container"
          else
            echo "Provider install failed; will retry in $check_interval seconds" >&2
          fi
        fi
      fi
    fi
  elif [[ ${#candidates[@]} -gt 1 ]]; then
    echo "More than one Music Assistant add-on found; set addon_container in this add-on's configuration." >&2
  fi

  sleep "$check_interval"
done
