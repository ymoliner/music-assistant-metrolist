# Music Assistant — Metrolist Listen Together

An experimental Music Assistant player provider that creates a Metrolist Listen Together room. Music Assistant is the room host; Metrolist joins as a guest and plays the YouTube Music tracks locally.

## Home Assistant OS add-on

The standard add-on cannot load a local provider ZIP or run `install.sh`. It uses an immutable container, and this script intentionally refuses to modify an add-on container. The supported Marketplace route is to publish a release and have the provider admitted to Music Assistant's community catalog. This repository has not been published or admitted yet.

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

## Setup

After installation, in Music Assistant open **Settings → Player Providers → Add** and select **Metrolist Listen Together**. Enter the Metro Server URL and room host name. The room code appears in the server log and the new player's name. In Metrolist, use **Listen Together → Join Room** and enter the code.

Only YouTube Music tracks can be played, because each Metrolist device resolves and streams the track itself. The provider has not been exercised against a live server and is experimental.

See [provider README](metrolist_listen_together/README.md) for details.
