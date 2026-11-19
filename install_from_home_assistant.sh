#!/usr/bin/env bash
set -euo pipefail

installer_url="https://raw.githubusercontent.com/ymoliner/music-assistant-metrolist/dad28a5d38759a86823797b9ce84334cda3b8574/install_device_connect.sh"
if ! command -v curl >/dev/null 2>&1; then
  echo "curl is required to fetch the installer from GitHub." >&2
  exit 2
fi
curl --fail --silent --show-error --location "$installer_url" | bash -s -- "$@"
