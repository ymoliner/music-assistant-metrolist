#!/usr/bin/env bash
set -euo pipefail

installer_url="https://raw.githubusercontent.com/ymoliner/music-assistant-metrolist/71a40279160b6bd8be533ab99dd0d82d6447562d/install_device_connect.sh"
if ! command -v curl >/dev/null 2>&1; then
  echo "curl is required to fetch the installer from GitHub." >&2
  exit 2
fi
curl --fail --silent --show-error --location "$installer_url" | bash -s -- "$@"
