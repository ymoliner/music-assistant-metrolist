"""Music Assistant player for a paired Metrolist Device Connect endpoint."""
from __future__ import annotations

import time
from typing import Any
from urllib.parse import parse_qs, urlparse

from music_assistant.models.player import Player, PlayerMedia
from music_assistant_models.enums import PlaybackState, PlayerFeature


class MetrolistDeviceConnectPlayer(Player):
    def __init__(self, provider: Any) -> None:
        super().__init__(provider, f"metrolist_dc_{provider.player_suffix}")
        self._attr_name = provider.player_name
        self._attr_available = False
        self._attr_powered = True
        self._attr_playback_state = PlaybackState.IDLE
        self._attr_supported_features = {
            PlayerFeature.PLAY_MEDIA, PlayerFeature.PAUSE, PlayerFeature.SEEK,
            PlayerFeature.POWER, PlayerFeature.NEXT_PREVIOUS,
        }
        self._session_id: str | None = None
        self._queue_revision = 0
        self._revision = 0
        self._track_revision = 0
        self._last_received_track_revision = 0
        self._position_ms = 0
        self._duration_ms = 0
        self._playing = False
        self._queue_tracks_cache: list[dict[str, Any]] = []
        self._queue_item_ids_cache: list[str | None] = []
        self._queue_source_id: str | None = None
        self._current_index = -1

    @property
    def needs_poll(self) -> bool:
        return True

    @property
    def poll_interval(self) -> int:
        return 1 if self._attr_playback_state == PlaybackState.PLAYING else 20

    async def play_media(self, media: PlayerMedia) -> None:
        tracks = self._queue_tracks(media)
        try:
            requested_track_id = self._track_for_media(media)
        except ValueError:
            # Queue items can have an opaque/unavailable MA URI even though the
            # selected queue row has a valid YouTube Music provider mapping.
            # _queue_tracks starts at that row when queue_item_id matched.
            requested_track_id = None
        current_index = next(
            (idx for idx, track in enumerate(tracks) if track["id"] == requested_track_id),
            None,
        )
        if current_index is None and requested_track_id is None and media.queue_item_id and media.source_id and tracks:
            current_index = 0
        if current_index is None:
            # Never silently start the first queue entry when the selected item
            # cannot be resolved from its queue row or YouTube Music URI.
            tracks = [self._song_from_media(media)]
            self._queue_item_ids_cache = [media.queue_item_id]
            current_index = 0
            self.provider.logger.warning(
                "Requested track was not found in the Music Assistant queue; "
                "sending the selected track alone"
            )
        self._queue_tracks_cache = tracks
        self._current_index = current_index
        self._last_received_track_revision = self._track_revision + 1
        self._session_id = self._session_id or self.provider.new_session_id()
        self._revision += 1
        self._queue_revision += 1
        self._track_revision += 1
        self._duration_ms = int((media.duration or 0) * 1000)
        self._position_ms = 0
        self._playing = True
        snapshot = {
            "sessionId": self._session_id,
            "revision": self._revision,
            "queueRevision": self._queue_revision,
            "trackRevision": self._track_revision,
            "anchorTimeMs": int(time.time() * 1000),
            "queueStateId": self.provider.new_session_id(),
            "playback": {
                "queue": {"displayedItems": tracks, "originalItems": tracks, "currentIndex": current_index,
                           "originalIndices": list(range(len(tracks)))},
                "title": self.provider.queue_title or "Music Assistant",
                "playing": True,
                "positionMs": 0,
                "durationMs": self._duration_ms,
                "ready": True,
            },
        }
        await self.provider.send_playback({"type": "TRANSFER", "sessionId": self._session_id, "snapshot": snapshot})
        self._attr_current_media = media
        self._attr_playback_state = PlaybackState.PLAYING
        self._attr_elapsed_time = 0
        self._attr_elapsed_time_last_updated = time.time()
        self.update_state()

    async def play(self) -> None:
        await self._command("PLAY")

    async def pause(self) -> None:
        await self._command("PAUSE")

    async def stop(self) -> None:
        await self.pause()
        self._attr_playback_state = PlaybackState.IDLE
        self.update_state()

    async def seek(self, position: int) -> None:
        self._position_ms = max(0, int(position * 1000))
        self.provider.logger.info(
            "Sending Metrolist seek to %d ms", self._position_ms
        )
        self._attr_elapsed_time = self._position_ms / 1000
        self._attr_elapsed_time_last_updated = time.time()
        self.update_state()
        await self._command("SEEK", positionMs=self._position_ms)

    async def next_track(self) -> None:
        await self._command("NEXT")

    async def previous_track(self) -> None:
        await self._command("PREVIOUS")

    async def power(self, powered: bool) -> None:
        self._attr_powered = powered
        if not powered:
            await self.pause()
        self.update_state()

    async def poll(self) -> None:
        now = time.time()
        if self._playing and self._attr_playback_state == PlaybackState.PLAYING:
            elapsed_ms = max(0, int((now - self._attr_elapsed_time_last_updated) * 1000))
            self._position_ms += elapsed_ms
            if self._duration_ms:
                self._position_ms = min(self._position_ms, self._duration_ms)
        self._attr_elapsed_time = self._position_ms / 1000
        self._attr_elapsed_time_last_updated = now
        self.update_state()

    async def _command(self, action: str, **kwargs: Any) -> None:
        if not self._session_id:
            return
        await self.provider.send_playback({"type": "COMMAND", "sessionId": self._session_id,
            "queueRevision": self._queue_revision,
            "command": {"action": action, **kwargs}})
        if action == "PLAY":
            self._playing = True
            self._attr_playback_state = PlaybackState.PLAYING
        elif action == "PAUSE":
            self._playing = False
            self._attr_playback_state = PlaybackState.PAUSED
        self.update_state()

    def receive_playback(self, message: dict[str, Any]) -> None:
        kind = message.get("type")
        if kind in {"STATE", "UPDATE"}:
            snapshot = message.get("snapshot") or {}
            playback = snapshot.get("playback") or {}
            if kind == "UPDATE" and ("positionMs" in message or message.get("seek", False) or "playing" in message):
                self.provider.logger.info(
                    "Metrolist playback update: index=%s, trackRevision=%s, position=%s ms, seek=%s, playing=%s",
                    message.get("index", "omitted"),
                    message.get("trackRevision", "omitted"),
                    message.get("positionMs", "omitted"),
                    message.get("seek", "omitted"),
                    message.get("playing", "omitted"),
                )
            queue = playback.get("queue") or {}
            items = queue.get("displayedItems")
            if isinstance(items, list):
                self._queue_tracks_cache = items
            if kind == "STATE":
                state_index = int(queue.get("currentIndex", message.get("index", self._current_index)))
                self.provider.logger.info(
                    "Metrolist state snapshot: index=%d, trackRevision=%s, queueItems=%d",
                    state_index,
                    message.get("trackRevision", snapshot.get("trackRevision", "omitted")),
                    len(items) if isinstance(items, list) else 0,
                )

            previous_index = self._current_index
            index = int(queue.get("currentIndex", message.get("index", self._current_index)))
            if index >= 0:
                self._current_index = index

            self._session_id = message.get("sessionId") or snapshot.get("sessionId") or self._session_id
            incoming_track_revision = int(
                message.get("trackRevision", snapshot.get("trackRevision", self._last_received_track_revision))
            )
            track_changed = incoming_track_revision != self._last_received_track_revision
            self._last_received_track_revision = incoming_track_revision
            snapshot_items = queue.get("displayedItems")
            if kind == "UPDATE" and track_changed and not isinstance(snapshot_items, list):
                # A phone-side next/previous may move onto a queue item that is
                # not in the cached MA queue. Ask the target for its authoritative
                # queue snapshot so the displayed track can be mapped correctly.
                self.provider.logger.info(
                    "Metrolist track revision changed (%d -> %d, index %d); requesting a fresh queue snapshot",
                    incoming_track_revision - 1,
                    incoming_track_revision,
                    index,
                )
                self.provider.mass.create_task(
                    self.provider.send_playback({
                        "type": "ATTACH",
                        "sessionId": self._session_id,
                    }),
                    task_name=f"metrolist-state-refresh-{self.provider.player_suffix}",
                )
            self._queue_revision = int(message.get("queueRevision", snapshot.get("queueRevision", self._queue_revision)))
            self._revision = int(message.get("revision", snapshot.get("revision", self._revision)))

            if "positionMs" in message:
                self._position_ms = max(0, int(message["positionMs"]))
            elif "positionMs" in playback:
                self._position_ms = max(0, int(playback["positionMs"]))
            elif kind == "UPDATE" and (message.get("seek", False) or (index >= 0 and index != previous_index)):
                # DcSyncMessage omits default-valued positionMs=0. A seek-to-zero
                # or new track therefore needs to reset the cached position.
                self._position_ms = 0
            elif snapshot and kind == "STATE":
                self._position_ms = 0

            if "durationMs" in message:
                self._duration_ms = max(0, int(message["durationMs"]))
            elif "durationMs" in playback:
                self._duration_ms = max(0, int(playback["durationMs"]))
            elif index >= 0 and index != previous_index and index < len(self._queue_tracks_cache):
                self._duration_ms = int(self._queue_tracks_cache[index].get("duration") or 0)

            if "playing" in message:
                self._playing = bool(message["playing"])
            elif snapshot:
                self._playing = bool(playback.get("playing", False))
            elif kind == "UPDATE":
                # Metrolist serializes playing=false as an omitted default field.
                self._playing = False

            queue_track_changed = False
            if 0 <= index < len(self._queue_tracks_cache):
                item = self._queue_tracks_cache[index]
                artists = item.get("artists") or []
                album = item.get("album") or {}
                item_id = str(item.get("id", ""))
                queue_item_id = (
                    self._queue_item_ids_cache[index]
                    if index < len(self._queue_item_ids_cache)
                    else None
                )
                previous_media = self._attr_current_media
                self._attr_current_media = PlayerMedia(
                    uri=f"ytmusic_free--{item_id}",
                    title=item.get("title"), artist=", ".join(a.get("name", "") for a in artists),
                    album=album.get("name"), duration=(self._duration_ms / 1000 if self._duration_ms else None),
                    image_url=item.get("thumbnail"),
                    source_id=self._queue_source_id,
                    queue_item_id=queue_item_id,
                )
                queue_track_changed = bool(
                    queue_item_id
                    and (previous_media is None or previous_media.queue_item_id != queue_item_id)
                )
            self._attr_playback_state = PlaybackState.PLAYING if self._playing else PlaybackState.PAUSED
            self._attr_elapsed_time = self._position_ms / 1000
            self._attr_elapsed_time_last_updated = time.time()
        elif kind == "RELEASE":
            self._session_id = None
            self._playing = False
            self._queue_tracks_cache = []
            self._queue_item_ids_cache = []
            self._queue_source_id = None
            self._current_index = -1
            self._position_ms = 0
            self._attr_playback_state = PlaybackState.IDLE
        self.update_state()
        if kind in {"STATE", "UPDATE"} and queue_track_changed and self._queue_source_id:
            # Music Assistant derives its queue's current item from the raw
            # protocol media. Notify it after a phone-side track transition.
            self.mass.player_queues.on_player_update(self, {})

    def _queue_tracks(self, media: PlayerMedia) -> list[dict[str, Any]]:
        # PlayerMedia.source_id is the queue ID that produced this request. Prefer it
        # over an inferred active queue, which can differ for synced or redirected players.
        queue = self.mass.player_queues.get(media.source_id) if media.source_id else None
        queue = queue or self.mass.player_queues.get_active_queue(self.player_id)
        self._queue_source_id = queue.queue_id if queue else media.source_id
        items: list[Any] = []
        if queue:
            items = list(self.mass.player_queues.items(queue.queue_id, limit=500))
            self.provider.queue_title = queue.display_name
        current = None
        if media.queue_item_id:
            current = next((i for i, row in enumerate(items) if row.queue_item_id == media.queue_item_id), None)
        source = items[current:] if current is not None else []
        tracks = []
        self._queue_item_ids_cache = []
        for row in source:
            if not row.media_item:
                continue
            try:
                tracks.append(self._song(row.media_item))
                self._queue_item_ids_cache.append(row.queue_item_id)
            except ValueError:
                if row.queue_item_id == media.queue_item_id:
                    domains = sorted({
                        str(getattr(mapping, "provider_domain", "") or "")
                        for mapping in (getattr(row.media_item, "provider_mappings", ()) or ())
                    })
                    self.provider.logger.warning(
                        "Selected Music Assistant queue row has no YouTube Music track ID "
                        "(mapping_domains=%s, uri_source=%s)",
                        ",".join(domains) or "none",
                        self._uri_source(getattr(row.media_item, "uri", None)),
                    )
                continue
        if not tracks and queue and media.queue_item_id:
            # The current item can sit beyond the bounded preview of a long queue.
            row = self.mass.player_queues.get_item(queue.queue_id, media.queue_item_id)
            if row and row.media_item:
                try:
                    tracks = [self._song(row.media_item)]
                    self._queue_item_ids_cache = [row.queue_item_id]
                except ValueError:
                    pass
        if not tracks:
            domains = sorted({
                str(getattr(mapping, "provider_domain", "") or "")
                for mapping in (getattr(media, "provider_mappings", ()) or ())
            })
            self.provider.logger.warning(
                "No mapped queue tracks were found for playback "
                "(queue_rows=%d, selected_queue_row_found=%s, media_mapping_domains=%s, "
                "uri_source=%s, original_uri_source=%s)",
                len(items),
                current is not None,
                ",".join(domains) or "none",
                self._uri_source(media.uri),
                self._uri_source((media.custom_data or {}).get("original_uri")),
            )
            tracks = [self._song_from_media(media)]
            self._queue_item_ids_cache = [media.queue_item_id]
        return tracks

    def _track_for_media(self, media: PlayerMedia) -> str:
        return self._song_from_media(media)["id"]

    @classmethod
    def _song(cls, item: Any) -> dict[str, Any]:
        item_id = None
        for mapping in getattr(item, "provider_mappings", ()) or ():
            provider = (getattr(mapping, "provider_domain", "") or "").lower()
            instance = (getattr(mapping, "provider_instance", "") or "").lower()
            if provider.startswith("ytmusic") or instance.startswith("ytmusic"):
                item_id = getattr(mapping, "item_id", None)
                if item_id:
                    break
        if not item_id:
            item_id = cls._id_from_uri(getattr(item, "uri", ""))
        if not item_id:
            raise ValueError("Queue item has no YouTube Music track mapping")
        artists = [{"id": getattr(a, "item_id", None), "name": getattr(a, "name", "")}
                   for a in (getattr(item, "artists", None) or [])]
        album = getattr(item, "album", None)
        metadata = getattr(item, "metadata", None)
        images = getattr(metadata, "images", None) or []
        return {"id": str(item_id), "title": getattr(item, "name", None) or str(item_id),
                "thumbnail": images[0].path if images else None, "artists": artists,
                "album": {"id": getattr(album, "item_id", None), "name": getattr(album, "name", "")} if album else None,
                "duration": int((getattr(item, "duration", None) or 0) * 1000)}

    @classmethod
    def _song_from_media(cls, media: PlayerMedia) -> dict[str, Any]:
        original_uri = (media.custom_data or {}).get("original_uri")
        item_id = cls._id_from_uri(media.uri) or cls._id_from_uri(original_uri)
        if not item_id:
            uri_source = cls._uri_source(media.uri)
            original_source = cls._uri_source(original_uri)
            raise ValueError(
                "Could not resolve this queue item to an original YouTube Music track "
                f"(uri_source={uri_source}, original_uri_source={original_source}, "
                f"queue_item={bool(media.queue_item_id)}, source_queue={bool(media.source_id)})"
            )
        artists = [{"id": None, "name": name.strip()} for name in (media.artist or "").split(",") if name.strip()]
        return {"id": item_id, "title": media.title or item_id, "thumbnail": media.image_url,
                "artists": artists, "album": {"id": None, "name": media.album} if media.album else None,
                "duration": int((media.duration or 0) * 1000)}

    @staticmethod
    def _id_from_uri(uri: str | None) -> str | None:
        if not uri:
            return None
        # Music Assistant provider URIs use "provider_instance--item_id".
        # YouTube Music Free therefore appears as "ytmusic_free--VIDEO_ID".
        if "://" not in uri:
            provider, separator, item_id = uri.partition("--")
            if separator and provider.lower().startswith("ytmusic"):
                value = item_id.strip("/")
                return value if 6 <= len(value) <= 32 else None

        # Accept YouTube Music custom schemes, whose underscore is not a valid
        # RFC URI scheme and therefore is not parsed normally by urllib.
        lowered = uri.lower()
        for prefix in ("ytmusic_free://", "ytmusic://"):
            if lowered.startswith(prefix):
                value = uri[len(prefix):].strip("/").rsplit("/", 1)[-1].split("?", 1)[0]
                return value if 6 <= len(value) <= 32 else None

        parsed = urlparse(uri)
        host = (parsed.hostname or "").lower()
        if host in {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}:
            value = (parse_qs(parsed.query).get("v") or [""])[0]
            return value if 6 <= len(value) <= 32 else None
        if host == "youtu.be":
            value = parsed.path.strip("/").split("/", 1)[0]
            return value if 6 <= len(value) <= 32 else None
        if not parsed.scheme.lower().startswith("ytmusic"):
            return None
        value = (parsed.netloc + parsed.path).strip("/").rsplit("/", 1)[-1]
        return value if 6 <= len(value) <= 32 else None

    @staticmethod
    def _uri_source(uri: str | None) -> str:
        """Return only the URI provider/scheme for safe diagnostics, never its full value."""
        if not uri:
            return "missing"
        if "--" in uri:
            return uri.split("--", 1)[0][:40]
        if "://" in uri:
            return uri.split("://", 1)[0][:40]
        return "unqualified"
