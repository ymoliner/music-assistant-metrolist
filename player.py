"""Music Assistant player representing a Metrolist Listen Together room."""

from __future__ import annotations

import time
from typing import Any
from urllib.parse import urlparse

from music_assistant.models.player import Player, PlayerMedia
from music_assistant_models.enums import PlaybackState, PlayerFeature

from .protocol import MetroSession


class MetrolistPlayer(Player):
    """A virtual player whose output is a Metrolist Listen Together room."""

    def __init__(self, provider: Any, session: MetroSession) -> None:
        super().__init__(provider, f"metrolist_{session.room_code.lower()}")
        self.session = session
        self._attr_name = f"Metrolist Room {session.room_code}"
        self._attr_supported_features = {
            PlayerFeature.PLAY_MEDIA,
            PlayerFeature.PAUSE,
            PlayerFeature.SEEK,
            PlayerFeature.POWER,
        }
        self._attr_powered = True
        self._attr_playback_state = PlaybackState.IDLE

    @property
    def needs_poll(self) -> bool:
        """Return True to keep the reported position in step with playback."""
        return True

    @property
    def poll_interval(self) -> int:
        """Return the player polling interval."""
        return 2 if self._attr_playback_state == PlaybackState.PLAYING else 30

    async def play_media(self, media: PlayerMedia) -> None:
        """Publish a YouTube Music track to the Metrolist room."""
        track = self._track_from_media(media)
        upcoming: list[dict[str, Any]] = []
        queue_title: str | None = None
        queue = self.mass.player_queues.get_active_queue(self.player_id)
        if queue:
            queue_title = queue.display_name
            items = self.mass.player_queues.items(queue.queue_id, limit=500)
            start = (queue.current_index + 1) if queue.current_index is not None else 0
            for item in items[start : start + 100]:
                if item.media_item is None:
                    continue
                try:
                    upcoming.append(self._track_from_item(item.media_item))
                except ValueError:
                    continue
        await self.session.publish_track(track, upcoming, queue_title)
        self._attr_current_media = media
        self._attr_playback_state = PlaybackState.PLAYING
        self.update_state()

    async def play(self) -> None:
        await self.session.control("play")
        self._attr_playback_state = PlaybackState.PLAYING
        self.update_state()

    async def pause(self) -> None:
        await self.session.control("pause")
        self._attr_playback_state = PlaybackState.PAUSED
        self.update_state()

    async def stop(self) -> None:
        await self.session.control("pause")
        self._attr_playback_state = PlaybackState.IDLE
        self.update_state()

    async def seek(self, position: int) -> None:
        await self.session.control("seek", position * 1000)
        self.update_state()

    async def power(self, powered: bool) -> None:
        self._attr_powered = powered
        if not powered:
            await self.stop()
        self.update_state()

    async def poll(self) -> None:
        self._attr_elapsed_time = self.session.position_ms // 1000
        self._attr_elapsed_time_last_updated = time.time()
        self.update_state()

    @staticmethod
    def _track_from_media(media: PlayerMedia) -> dict[str, Any]:
        parsed = urlparse(media.uri)
        provider = parsed.scheme.lower()
        if not provider.startswith("ytmusic"):
            raise ValueError(
                "Metrolist Listen Together can only play YouTube Music tracks; "
                f"this item came from {provider or 'an unsupported source'}"
            )
        item_id = parsed.netloc + parsed.path
        item_id = item_id.strip("/")
        if "/" in item_id:
            item_id = item_id.rsplit("/", 1)[-1]
        if not item_id or len(item_id) < 6 or len(item_id) > 32:
            raise ValueError(f"Cannot derive a YouTube Music video ID from {media.uri!r}")
        return {
            "id": item_id,
            "title": media.title or item_id,
            "artist": media.artist or "",
            "album": media.album,
            "duration": int((media.duration or 0) * 1000),
            "thumbnail": media.image_url,
        }

    @staticmethod
    def _track_from_item(item: Any) -> dict[str, Any]:
        uri = item.uri
        parsed = urlparse(uri)
        provider = parsed.scheme.lower()
        if not provider.startswith("ytmusic"):
            raise ValueError(f"Not a YouTube Music item: {uri!r}")
        item_id = (parsed.netloc + parsed.path).strip("/").rsplit("/", 1)[-1]
        if not item_id or len(item_id) < 6 or len(item_id) > 32:
            raise ValueError(f"Cannot derive a YouTube Music video ID from {uri!r}")
        artists = getattr(item, "artists", None) or []
        album = getattr(item, "album", None)
        metadata = getattr(item, "metadata", None)
        images = getattr(metadata, "images", None) or []
        return {
            "id": item_id,
            "title": getattr(item, "name", None) or item_id,
            "artist": ", ".join(artist.name for artist in artists),
            "album": getattr(album, "name", None),
            "duration": int((getattr(item, "duration", None) or 0) * 1000),
            "thumbnail": images[0].path if images else None,
        }
