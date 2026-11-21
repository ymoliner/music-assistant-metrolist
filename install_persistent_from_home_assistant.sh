#!/usr/bin/env bash
set -euo pipefail

repo="ymoliner/music-assistant-metrolist"
branch="${METROLIST_DEVICE_CONNECT_REF:-main}"
relative_addon="metrolist_device_connect_keeper"
stage="$(mktemp -d)"
trap 'rm -rf "$stage"' EXIT
stage_addon="$stage/$relative_addon"

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker CLI is unavailable. Run this from a Home Assistant terminal with Docker access." >&2
  exit 2
fi
if ! command -v curl >/dev/null 2>&1; then
  echo "curl is required to download the provider and helper." >&2
  exit 2
fi

mkdir -p "$stage_addon/provider"
for file in config.yaml Dockerfile run.sh README.md; do
  curl --fail --silent --show-error --location \
    "https://raw.githubusercontent.com/$repo/$branch/$relative_addon/$file" \
    --output "$stage_addon/$file"
done
for file in __init__.py account.py session.py player.py setup_flow.py manifest.json VERSION; do
  curl --fail --silent --show-error --location \
    "https://raw.githubusercontent.com/$repo/$branch/metrolist_device_connect/$file" \
    --output "$stage_addon/provider/$file"
done
chmod +x "$stage_addon/run.sh"

addon_dir="/addons/$relative_addon"
if [[ -d /addons && -w /addons ]]; then
  if [[ -e "$addon_dir/config.yaml" ]] &&
     ! grep -q "^slug: $relative_addon$" "$addon_dir/config.yaml"; then
    echo "Refusing to overwrite an unrelated local add-on at $addon_dir." >&2
    exit 2
  fi
  mkdir -p /addons
  cp -a "$stage_addon" "$addon_dir"
else
  supervisor_container=""
  while IFS= read -r name; do
    if docker exec "$name" test -d /addons >/dev/null 2>&1; then
      supervisor_container="$name"
      break
    fi
  done < <(docker ps --format '{{.Names}}' | while IFS= read -r n; do
    if [[ "$n" == *supervisor* ]]; then printf '%s\n' "$n"; fi
  done)
  if [[ -z "$supervisor_container" ]]; then
    echo "Could not find a writable Home Assistant /addons folder or Supervisor container." >&2
    echo "Run this in the Home Assistant host terminal with Docker access." >&2
    exit 2
  fi
  existing_config="$(docker exec "$supervisor_container" cat "/addons/$relative_addon/config.yaml" 2>/dev/null || true)"
  if [[ -n "$existing_config" ]] && ! grep -q "^slug: $relative_addon$" <<<"$existing_config"; then
    echo "Refusing to overwrite an unrelated local add-on at /addons/$relative_addon." >&2
    exit 2
  fi
  docker exec "$supervisor_container" mkdir -p "/addons/$relative_addon"
  docker cp "$stage_addon/." "$supervisor_container:/addons/$relative_addon/"
fi

installer="$stage/install_device_connect.sh"
curl --fail --silent --show-error --location \
  "https://raw.githubusercontent.com/$repo/$branch/install_device_connect.sh" \
  --output "$installer"
bash "$installer" "${1:-}"

cat <<'EOF'
Persistent helper files are ready under Home Assistant's /addons folder.
In Home Assistant, refresh the local app/add-on store, install "Metrolist Provider Keeper",
turn Protection mode off for that add-on, then start it and enable Start on boot.
Leave its container name blank unless more than one Music Assistant add-on is running.
EOF
