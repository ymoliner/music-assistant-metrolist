# Metrolist Provider Keeper

This local Home Assistant add-on keeps the manually installed Metrolist Device Connect provider present after the Music Assistant add-on's container is replaced or updated. It checks every 30 seconds and copies the bundled provider only when its version marker is missing or different.

## Install

Run the repository's `install_persistent_from_home_assistant.sh` from a Home Assistant host terminal with Docker access. It creates this local add-on under `/addons/metrolist_device_connect_keeper` and performs the initial provider install.

Then in Home Assistant:

1. Open **Settings → Apps → App store** (or **Settings → Add-ons → Add-on store** on older versions) and refresh/reload local apps.
2. Open **Metrolist Provider Keeper**, install it, and turn **Protection mode** off for this add-on. Start it and enable **Start on boot**.
3. Leave its container name blank for auto-detection. If more than one Music Assistant add-on runs, enter the container name shown by `docker ps`.

This add-on needs Docker API access to copy files into the Music Assistant container and restart it after an update. Home Assistant only exposes that socket when protection mode is off. Its code is local under `/addons`; it starts at boot and keeps retrying while Music Assistant is starting.

To update the provider code later, rerun the persistent installer and rebuild/reinstall this local add-on so its bundled provider files update.
