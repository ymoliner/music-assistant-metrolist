"""Music Assistant player for local playback in Metrolist on Android."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote, urlparse

from music_assistant.models.player import Player, PlayerMedia
from music_assistant_models.enums import PlaybackState, PlayerFeature


class MetrolistLocalPlayer(Player):
    """Send track links and media commands to one Android Metrolist app."""

    def __init__(self, provider: Any, notify_service: str) -> None:
        suffix = notify_service.removeprefix("mobile_app_")
        slug = re.sub(r"[^a-z0-9_]+", "_", suffix.lower()).strip("_") or "phone"
        super().__init__(provider, f"metrolist_local_{slug}")
        self.notify_service = notify_service
        self.android_package = provider.android_package
        self._attr_name = f"Metrolist ({suffix})"
        self._attr_supported_features = {
            PlayerFeature.PLAY_MEDIA,
            PlayerFeature.PAUSE,
        }
        self._attr_available = True
        self._attr_powered = True
        self._attr_playback_state = PlaybackState.IDLE

    async def play_media(self, media: PlayerMedia) -> None:
        """Open the selected YouTube Music track in Metrolist on the phone."""
        video_id = self._video_id_for_media(media)
        await self.provider.send_phone_command(
            self.notify_service,
            "command_activity",
            {
                "intent_action": "android.intent.action.VIEW",
                "intent_package_name": self.android_package,
                "intent_uri": f"https://music.youtube.com/watch?v={quote(video_id)}",
            },
        )
        self._attr_current_media = media
        self._attr_playback_state = PlaybackState.PLAYING
        self.update_state()

    async def play(self) -> None:
        await self._send_media_command("play")
        self._attr_playback_state = PlaybackState.PLAYING
        self.update_state()

    async def pause(self) -> None:
        await self._send_media_command("pause")
        self._attr_playback_state = PlaybackState.PAUSED
        self.update_state()

    async def stop(self) -> None:
        await self._send_media_command("stop")
        self._attr_playback_state = PlaybackState.IDLE
        self.update_state()

    async def _send_media_command(self, command: str) -> None:
        await self.provider.send_phone_command(
            self.notify_service,
            "command_media",
            {"media_command": command, "media_package_name": self.android_package},
        )

    def _video_id_for_media(self, media: PlayerMedia) -> str:
        """Read the original provider mapping from Music Assistant's queue item."""
        queue = self.mass.player_queues.get_active_queue(self.player_id)
        if queue and media.queue_item_id:
            for queue_item in self.mass.player_queues.items(queue.queue_id, limit=500):
                if queue_item.queue_item_id == media.queue_item_id and queue_item.media_item:
                    item_id = self._video_id_for_item(queue_item.media_item)
                    if item_id:
                        return item_id
        item_id = self._video_id_from_uri(media.uri)
        if item_id:
            return item_id
        raise ValueError(
            "Could not find a YouTube Music video ID for this item. "
            "Choose a track with a YouTube Music provider mapping."
        )

    @classmethod
    def _video_id_for_item(cls, item: Any) -> str | None:
        for mapping in getattr(item, "provider_mappings", ()) or ():
            domain = (getattr(mapping, "provider_domain", "") or "").lower()
            instance = (getattr(mapping, "provider_instance", "") or "").lower()
            item_id = getattr(mapping, "item_id", None)
            if (domain.startswith("ytmusic") or instance.startswith("ytmusic")) and item_id:
                return str(item_id)
        return cls._video_id_from_uri(getattr(item, "uri", ""))

    @staticmethod
    def _video_id_from_uri(uri: str | None) -> str | None:
        if not uri:
            return None
        parsed = urlparse(uri)
        if not parsed.scheme.lower().startswith("ytmusic"):
            return None
        item_id = (parsed.netloc + parsed.path).strip("/").rsplit("/", 1)[-1]
        return item_id if 6 <= len(item_id) <= 32 else None
