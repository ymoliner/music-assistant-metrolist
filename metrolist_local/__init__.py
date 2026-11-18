"""Music Assistant player provider for direct local Metrolist playback."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from music_assistant.models.player_provider import PlayerProvider
from music_assistant_models.enums import ProviderFeature

from .player import MetrolistLocalPlayer

if TYPE_CHECKING:
    from music_assistant_models.config_entries import ConfigEntry, ProviderConfig
    from music_assistant_models.provider import ProviderManifest

    from music_assistant.mass import MusicAssistant
    from music_assistant.models import ProviderInstanceType


SUPPORTED_FEATURES: set[ProviderFeature] = set()


async def setup(
    mass: MusicAssistant, manifest: ProviderManifest, config: ProviderConfig
) -> ProviderInstanceType:
    """Set up players backed by Android Home Assistant Companion apps."""
    return MetrolistLocalProvider(mass, manifest, config, SUPPORTED_FEATURES)


class MetrolistLocalProvider(PlayerProvider):
    """Expose one local Metrolist player for each configured Android phone."""

    _local_players: dict[str, MetrolistLocalPlayer]
    hass_provider: Any
    android_package: str

    async def get_config_entries(self) -> tuple[ConfigEntry, ...]:
        """Collect one Home Assistant mobile_app notify target per phone."""
        from music_assistant_models.config_entries import ConfigEntry
        from music_assistant_models.enums import ConfigEntryType

        return (
            ConfigEntry(
                key="notify_services",
                type=ConfigEntryType.STRING,
                label="Android phone notification services",
                description=(
                    "Add one service suffix per phone, for example mobile_app_pixel_8. "
                    "Find it in Home Assistant under Developer Tools → Actions as "
                    "notify.mobile_app_<phone>. Do not enter a phone IP."
                ),
                multi_value=True,
                required=True,
                default_value=[],
            ),
            ConfigEntry(
                key="android_package",
                type=ConfigEntryType.STRING,
                label="Metrolist Android package",
                description="Release build: com.metrolist.music. Debug builds may differ.",
                required=True,
                default_value="com.metrolist.music",
            ),
        )

    async def handle_async_init(self) -> None:
        """Register the selected phones as separate Music Assistant players."""
        self.hass_provider = self.mass.get_provider("hass")
        if self.hass_provider is None or not self.hass_provider.hass.connected:
            raise RuntimeError(
                "The Home Assistant plugin must be configured before Metrolist Local Playback."
            )
        self.android_package = str(
            self.config.get_value("android_package", "com.metrolist.music")
        ).strip()
        services = self.config.get_value("notify_services", []) or []
        self._local_players = {}
        for raw_service in services:
            service = str(raw_service).strip()
            if service.startswith("notify."):
                service = service.partition(".")[2]
            if not service.startswith("mobile_app_"):
                raise ValueError(
                    f"{raw_service!r} must be a Home Assistant mobile_app notify service."
                )
            player = MetrolistLocalPlayer(self, service)
            if player.player_id in self._local_players:
                continue
            self._local_players[player.player_id] = player
            await self.mass.players.register(player)

    async def unload(self, is_removed: bool = False) -> None:
        """Unregister phone players before unloading this provider."""
        for player_id in tuple(getattr(self, "_local_players", {})):
            if self.mass.players.get_player(player_id):
                await self.mass.players.unregister(player_id)
        await super().unload(is_removed)

    async def send_phone_command(self, service: str, message: str, data: dict[str, Any]) -> None:
        """Send a Home Assistant Companion command to one Android phone."""
        await self.hass_provider.hass.call_service(
            domain="notify",
            service=service,
            service_data={"message": message, "data": data},
        )
