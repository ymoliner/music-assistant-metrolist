#!/usr/bin/env bash
set -euo pipefail

repo="ymoliner/music-assistant-metrolist"
branch="${METROLIST_DEVICE_CONNECT_REF:-main}"
addon_dir="/addons/metrolist_device_connect_keeper"

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker CLI is unavailable. Run this from a Home Assistant host terminal with Docker access." >&2
  exit 2
fi
if [[ ! -d /addons || ! -w /addons ]]; then
  echo "The Home Assistant local-apps folder /addons is not writable from this terminal." >&2
  echo "Use an SSH/Terminal session with host access, not a terminal inside another add-on." >&2
  exit 2
fi
if [[ -e "$addon_dir/config.yaml" ]] &&
   ! grep -q '^slug: metrolist_device_connect_keeper$' "$addon_dir/config.yaml"; then
  echo "Refusing to overwrite an unrelated local add-on at $addon_dir." >&2
  exit 2
fi

mkdir -p "$addon_dir/provider"
for file in config.yaml Dockerfile run.sh README.md; do
  curl --fail --silent --show-error --location \
    "https://raw.githubusercontent.com/$repo/$branch/metrolist_device_connect_keeper/$file" \
    --output "$addon_dir/$file"
done
for file in __init__.py account.py session.py player.py setup_flow.py manifest.json VERSION; do
  curl --fail --silent --show-error --location \
    "https://raw.githubusercontent.com/$repo/$branch/metrolist_device_connect/$file" \
    --output "$addon_dir/provider/$file"
done
chmod +x "$addon_dir/run.sh"

installer="$(mktemp)"
trap 'rm -f "$installer"' EXIT
curl --fail --silent --show-error --location \
  "https://raw.githubusercontent.com/$repo/$branch/install_device_connect.sh" \
  --output "$installer"
bash "$installer" "${1:-}"

cat <<'EOF'
Persistent provider helper files are ready under /addons/metrolist_device_connect_keeper.
In Home Assistant, refresh the local app/add-on store, install "Metrolist Provider Keeper",
turn Protection mode off for that add-on, then start it and enable Start on boot.
Leave its container name blank unless more than one Music Assistant add-on is running.
EOF
