# Music Assistant — Metrolist Providers

This repository contains two experimental player providers:

- **Metrolist Listen Together** sends tracks to a Metro Server room; phones join the room in Metrolist.
- **Metrolist Local Playback** opens the selected YouTube Music track directly in Metrolist on Android through the Home Assistant Companion App. It does not use Listen Together or Metro Server.

## Home Assistant OS add-on

The standard add-on does not offer a supported local-provider installer. Providers can be copied into its running container, but an add-on image update removes those files. A Marketplace release would require admission to Music Assistant's community catalog; this repository is not listed there.

## Docker install

On the Docker host, extract this repository and run:

```sh
./install.sh
```

If more than one Music Assistant container is running, pass its container name:

```sh
./install.sh music-assistant
```

This installs into the running container and restarts it. Container replacement or image updates remove the installed files; re-run the script afterward.

## Home Assistant add-on setup

For a manually installed provider, copy its provider directory into `music_assistant/providers/` inside the add-on container and restart it.

For **Metrolist Local Playback**, configure the Home Assistant plugin first, then add the provider and enter one `notify.mobile_app_<phone>` service suffix per Android phone. Each phone becomes its own Music Assistant player. The phone needs the Home Assistant Companion App; no phone IP or Metro Server URL is used.

For **Metrolist Listen Together**, add that provider and configure the Metro Server URL and room host name. Join the generated room code from Metrolist.

See [local provider README](metrolist_local/README.md) and [Listen Together README](metrolist_listen_together/README.md).

