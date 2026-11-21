# Metrolist Device Connect

This experimental Music Assistant player provider implements a direct connection to Metrolist's Device Connect WebSocket endpoint. Add one provider instance per Metrolist installation (for example, one for a phone and one for a PC). Each instance pairs independently and gets its own named Music Assistant player.

## Configure

1. In Metrolist, enable Device Connect and note the listening port.
2. Find an IP address reachable from the Music Assistant add-on. Enter `ws://DEVICE_IP:PORT/connect` as the endpoint. Use a Tailscale address if that is the route between the add-on and device.
3. In Music Assistant, add this provider and enter the full YouTube Music cookie header and the matching `dataSyncId`. Both are secure fields. Do not share them in chat, logs, or screenshots.
4. When Metrolist shows a pairing code, compare it with the code in Music Assistant's provider log, then approve the same code in Metrolist. The provider stores only the peer device ID and derived pair secret for later reconnects.

The account cookie must include `SAPISID`, `__Secure-3PAPISID`, or `__Secure-1PAPISID`. Use the same signed-in YouTube Music account in Metrolist and the cookie source. A `dataSyncId` is required for account matching.

## Persistent Home Assistant installation\n\nRun `install_persistent_from_home_assistant.sh` from a host terminal with Docker access, then refresh the local app/add-on store and install **Metrolist Provider Keeper**. Turn off Protection mode for that add-on, start it, and enable Start on boot. The keeper restores the provider when Music Assistant's container is replaced or updated. It uses the Home Assistant Docker API socket. See [the keeper guide](../metrolist_device_connect_keeper/README.md).\n\n## Manual installation in a Home Assistant Music Assistant add-on

This provider is not yet in the Music Assistant Marketplace. On the Docker host that runs Home Assistant, copy this directory into the add-on's `music_assistant/providers` directory and restart the add-on. From a checkout or extracted archive:

```sh
./install_device_connect.sh <music-assistant-addon-container>
```

Find the container name with `docker ps`. The script refuses a non add-on Music Assistant container and installs only `metrolist_device_connect`. Container replacement or add-on image updates remove manually copied files; rerun the installer after such an update. The script does not alter the existing Listen Together or Metrolist Local providers.

## Current scope

The provider implements direct endpoint connection, encrypted v2 framing, account-scoped code pairing, saved-pair reconnect, playback chunk assembly, player state mapping, controls, and YouTube Music queue transfer. The first connection requires approval in Metrolist. Use a LAN or Tailscale route that the add-on can reach; the endpoint is not exposed through a relay.
