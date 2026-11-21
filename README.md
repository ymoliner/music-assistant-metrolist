# Music Assistant — Metrolist Providers

This repository contains three experimental player providers:

- **Metrolist Device Connect** is an experimental provider for direct Device Connect pairing, playback state, controls, and queue transfer. Live device pairing and playback have not yet been verified.
- **Metrolist Listen Together** sends tracks to a Metro Server room; phones join the room in Metrolist.
- **Metrolist Local Playback** opens YouTube Music tracks in Metrolist on Android through the Home Assistant Companion App.

## Home Assistant add-on install

On a Home Assistant host shell with Docker access, run:

```sh
bash <(curl -fsSL https://raw.githubusercontent.com/ymoliner/music-assistant-metrolist/main/install_from_home_assistant.sh)
```

The installer downloads the provider files from this repository, copies them into the running Music Assistant add-on, and restarts it. If more than one Music Assistant add-on is running, pass its container name as the final argument. Manually copied files are removed when the add-on container is replaced or updated; rerun the installer after such an update. An ordinary Terminal & SSH add-on may not have access to the host Docker socket.

After restart, add **Metrolist Device Connect** in Music Assistant → Settings → Player Providers. Enter the Metrolist WebSocket endpoint ending in `/connect` and provide the cookie and matching `dataSyncId` through the secure fields. Compare the pairing codes in Music Assistant and Metrolist, then approve the same code in Metrolist. See [the provider guide](metrolist_device_connect/README.md).

## Persistent Home Assistant install\n\nTo restore the provider automatically after the Music Assistant add-on container is replaced or updated, run:\n\n```sh\nbash <(curl -fsSL https://raw.githubusercontent.com/ymoliner/music-assistant-metrolist/main/install_persistent_from_home_assistant.sh)\n```\n\nThen refresh the local app/add-on store, install **Metrolist Provider Keeper**, turn off Protection mode for it, and start it with **Start on boot** enabled. The helper checks every 30 seconds and restores the provider if needed. It requires the Docker API socket. Details are in [the keeper guide](metrolist_device_connect_keeper/README.md).\n\nAdd one **Metrolist Device Connect** provider instance per Metrolist installation. Give each a distinct name such as **Phone** and **PC**; each instance pairs independently.\n\n## Docker install

`install.sh` remains the installer for the older Listen Together provider on a regular Docker-hosted Music Assistant server. See [Metrolist Local Playback](metrolist_local/README.md) and [Metrolist Listen Together](metrolist_listen_together/README.md) for their setup flows.
