#!/usr/bin/env bash
set -euo pipefail

installer_url="https://raw.githubusercontent.com/ymoliner/music-assistant-metrolist/7f129e74f06163499fd16623ccc77dcfe7768881/install_device_connect.sh"
if ! command -v curl >/dev/null 2>&1; then
  echo "curl is required to fetch the installer from GitHub." >&2
  exit 2
fi
curl --fail --silent --show-error --location "$installer_url" | bash -s -- "$@"
