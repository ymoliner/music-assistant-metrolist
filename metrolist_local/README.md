# Metrolist Local Playback for Music Assistant

This experimental player provider sends selected YouTube Music track links to Metrolist on Android. The phone streams the song itself; it does not join a Listen Together room, and Metro Server is not used.

## Requirements

- The Music Assistant Home Assistant plugin is configured.
- Home Assistant Companion App is installed on each target Android phone and connected to the same Home Assistant instance.
- The Companion App has notification permission. Its first `command_activity` may require Android's **Display over other apps** permission.
- The phone has Metrolist installed. Release package name: `com.metrolist.music`.
- The selected Music Assistant item has a YouTube Music provider mapping.

## Configure

Add **Metrolist Local Playback** under Music Assistant **Settings → Player Providers**. In **Android phone notification services**, add one value per phone, using the suffix of the Home Assistant notify service. For example, if Home Assistant shows `notify.mobile_app_pixel_8`, enter `mobile_app_pixel_8`.

Each configured phone appears as a separate Music Assistant player. There are no phone IPs to enter: Music Assistant uses Home Assistant's Companion App notification channel to open the selected YouTube Music link in Metrolist. The phone must be online and able to receive Home Assistant notifications.

## Limits

- Playback starts by opening a YouTube Music track URL in Metrolist. Android, the Companion App, and Metrolist must allow that app link to open and play.
- Play/Pause/Stop use Android's active media session. This provider does not read the phone's live playback state, seek position, or volume.
- Music Assistant's queue supplies the track selected through its UI; this does not synchronize the Metrolist app's own queue or history.
- No Listen Together room or Metro Server is involved.
