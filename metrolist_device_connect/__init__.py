"""Music Assistant player provider for Metrolist Device Connect."""
from __future__ import annotations

import asyncio
import json
import re
import secrets
import time
import uuid
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from music_assistant.models.player_provider import PlayerProvider
from music_assistant_models.enums import ProviderFeature

from .player import MetrolistDeviceConnectPlayer
from .session import DeviceConnectSession

if TYPE_CHECKING:
    from music_assistant_models.config_entries import ConfigEntry, ProviderConfig
    from music_assistant_models.provider import ProviderManifest
    from music_assistant.mass import MusicAssistant
    from music_assistant.models import ProviderInstanceType

SUPPORTED_FEATURES: set[ProviderFeature] = set()


async def setup(mass: MusicAssistant, manifest: ProviderManifest, config: ProviderConfig) -> ProviderInstanceType:
    return MetrolistDeviceConnectProvider(mass, manifest, config, SUPPORTED_FEATURES)


class MetrolistDeviceConnectProvider(PlayerProvider):
    player: MetrolistDeviceConnectPlayer
    session: DeviceConnectSession | None = None
    connection_task: asyncio.Task[None] | None = None
    queue_title: str | None = None

    async def get_config_entries(self) -> tuple[ConfigEntry, ...]:
        """Provider-specific values are collected by setup_flow.py."""
        return ()

    async def handle_async_init(self) -> None:
        endpoint = str(self.get_setup_value("endpoint", "") or "").strip()
        parsed = urlparse(endpoint)
        if parsed.scheme not in {"ws", "wss"} or not parsed.hostname or parsed.path != "/connect":
            raise ValueError("Enter a reachable ws:// or wss:// endpoint ending in /connect")
        self.endpoint = endpoint
        self.cookie = str(self.get_setup_value("cookie", "") or "")
        self.data_sync_id = str(self.get_setup_value("data_sync_id", "") or "")
        if not self.cookie or not self.data_sync_id:
            raise ValueError("A YouTube Music cookie and Metrolist dataSyncId are required")
        self.device_name = str(self.get_setup_value("device_name", "Music Assistant") or "Music Assistant").strip() or "Music Assistant"
        self.device_id = str(self.get_setup_value("device_id", "") or secrets.token_urlsafe(9))
        self._update_setup_data("device_id", self.device_id, immediate=True)
        try:
            state = json.loads(str(self.get_setup_value("pair_state", "{}") or "{}"))
            self.peer_id = str(state.get("peer_id", ""))
            self.pair_secret = str(state.get("pair_secret", ""))
        except (TypeError, ValueError):
            self.peer_id, self.pair_secret = "", ""
        suffix = re.sub(r"[^a-z0-9]+", "_", self.device_id.lower()).strip("_")[:16]
        self.player_suffix = suffix or "device"
        self.player_name = "Metrolist Device Connect"
        self.player = MetrolistDeviceConnectPlayer(self)
        await self.mass.players.register(self.player)
        self.connection_task = asyncio.create_task(self._connection_loop(), name=f"metrolist-dc-{suffix}")

    def new_session_id(self) -> str:
        return str(uuid.uuid4())

    async def send_playback(self, message: dict[str, Any]) -> None:
        if not self.session or not self.session.connected:
            raise RuntimeError("Metrolist Device Connect is not paired or connected")
        await self.session.send_playback(message)

    def _save_pair(self, peer_id: str, pair_secret: str) -> None:
        self.peer_id = peer_id
        self.pair_secret = pair_secret
        self._update_setup_data("pair_state", json.dumps({"peer_id": peer_id, "pair_secret": pair_secret}), immediate=True)

    def _receive_playback(self, message: dict[str, Any]) -> None:
        self.player.receive_playback(message)

    async def _connection_loop(self) -> None:
        delay = 3
        while True:
            session = DeviceConnectSession(
                url=self.endpoint, device_id=self.device_id, device_name=self.device_name,
                cookie=self.cookie, data_sync_id=self.data_sync_id, peer_id=self.peer_id,
                pair_secret=self.pair_secret, save_pair=self._save_pair, logger=self.logger,
                on_playback=self._receive_playback,
            )
            self.session = session
            try:
                await session.connect()
                self.player._attr_available = True
                self.player.update_state()
                delay = 3
                await session.run()
            except asyncio.CancelledError:
                raise
            except Exception as err:
                # Include only a whitelisted protocol field name for KeyError diagnostics.
                missing = (
                    str(err.args[0])
                    if isinstance(err, KeyError) and err.args and err.args[0] in {
                        "payload", "commitment", "version", "role", "deviceId", "nonce", "publicKey"
                    }
                    else ""
                )
                detail = f", missing field {missing}" if missing else ""
                self.logger.warning(
                    "Metrolist Device Connect failed during %s (%s%s); retrying.",
                    session.stage,
                    type(err).__name__,
                    detail,
                )
            finally:
                await session.close()
                self.session = None
                self.player._attr_available = False
                self.player.update_state()
            await asyncio.sleep(delay)
            delay = min(delay * 2, 60)

    async def unload(self, is_removed: bool = False) -> None:
        if self.connection_task:
            self.connection_task.cancel()
            await asyncio.gather(self.connection_task, return_exceptions=True)
        if self.session:
            await self.session.close()
        if getattr(self, "player", None) and self.mass.players.get_player(self.player.player_id):
            await self.mass.players.unregister(self.player.player_id)
        self.cookie = ""
        self.data_sync_id = ""
        await super().unload(is_removed)

    async def discover_players(self) -> None:
        if getattr(self, "player", None) and not self.mass.players.get_player(self.player.player_id):
            await self.mass.players.register(self.player)
