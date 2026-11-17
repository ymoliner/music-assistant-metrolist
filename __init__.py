"""Music Assistant player provider for Metrolist Listen Together."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from music_assistant_models.enums import ProviderFeature
from music_assistant.models.player_provider import PlayerProvider

from .player import MetrolistPlayer
from .protocol import MetroSession

if TYPE_CHECKING:
    from music_assistant_models.config_entries import ConfigEntry
    from music_assistant_models.config_entries import ProviderConfig
    from music_assistant_models.provider import ProviderManifest

    from music_assistant.mass import MusicAssistant
    from music_assistant.models import ProviderInstanceType


SUPPORTED_FEATURES: set[ProviderFeature] = set()


async def setup(
    mass: MusicAssistant, manifest: ProviderManifest, config: ProviderConfig
) -> ProviderInstanceType:
    """Create a Metrolist provider instance."""
    return MetrolistProvider(mass, manifest, config, SUPPORTED_FEATURES)


class MetrolistProvider(PlayerProvider):
    """Host one Metrolist Listen Together room as a Music Assistant player."""

    session: MetroSession | None = None
    room_task: asyncio.Task[None] | None = None
    player: MetrolistPlayer | None = None

    async def get_config_entries(self) -> tuple[ConfigEntry, ...]:
        """Return connection settings."""
        from music_assistant_models.config_entries import ConfigEntry
        from music_assistant_models.enums import ConfigEntryType

        return (
            ConfigEntry(
                key="server_url",
                type=ConfigEntryType.STRING,
                label="Metro Server WebSocket URL",
                default_value="wss://metroserverx.meowery.eu/ws",
                required=True,
                description="Metrolist Listen Together server URL.",
            ),
            ConfigEntry(
                key="username",
                type=ConfigEntryType.STRING,
                label="Room host name",
                default_value="Music Assistant",
                required=True,
            ),
        )

    async def handle_async_init(self) -> None:
        """Connect to Metro Server and create a room."""
        url = str(self.config.get_value("server_url", "wss://metroserverx.meowery.eu/ws"))
        username = str(self.config.get_value("username", "Music Assistant"))
        self.session = MetroSession(self, url, username)
        try:
            await self.session.connect_and_create()
        except Exception:
            await self.session.close()
            self.session = None
            raise
        self.player = MetrolistPlayer(self, self.session)
        await self.mass.players.register(self.player)
        self.room_task = asyncio.create_task(self.session.run(), name="metrolist-room")

    async def unload(self, is_removed: bool = False) -> None:
        """Close the Metro Server connection."""
        if self.room_task:
            self.room_task.cancel()
            await asyncio.gather(self.room_task, return_exceptions=True)
            self.room_task = None
        if self.player:
            await self.mass.players.unregister(self.player.player_id)
            self.player = None
        if self.session:
            await self.session.close()
            self.session = None

    async def discover_players(self) -> None:
        """Re-register the room player after a discovery request."""
        if self.player and not self.mass.players.get_player(self.player.player_id):
            await self.mass.players.register(self.player)
