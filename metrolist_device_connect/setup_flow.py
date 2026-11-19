"""Initial and reconfiguration form for Metrolist Device Connect."""
from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from music_assistant.models.setup_flow import SetupFlowError
from music_assistant_models.config_entries import ConfigEntry
from music_assistant_models.enums import ConfigEntryType

if TYPE_CHECKING:
    from music_assistant.models.setup_flow import SetupSession

_ENTRIES = (
    ConfigEntry(
        key="endpoint",
        type=ConfigEntryType.STRING,
        label="Metrolist Device Connect WebSocket URL",
        description="Enter the phone's current ws://IP:PORT/connect for initial pairing. After pairing, Music Assistant follows the phone's mDNS-advertised endpoint.",
        required=True,
    ),
    ConfigEntry(
        key="cookie",
        type=ConfigEntryType.SECURE_STRING,
        label="YouTube Music cookie",
        description="Paste the full cookie header. This is stored securely; never paste it into chat or logs.",
        required=True,
    ),
    ConfigEntry(
        key="data_sync_id",
        type=ConfigEntryType.SECURE_STRING,
        label="Metrolist dataSyncId",
        description="Required with the cookie to identify the same YouTube Music account.",
        required=True,
    ),
    ConfigEntry(
        key="device_name",
        type=ConfigEntryType.STRING,
        label="Music Assistant device name",
        default_value="Music Assistant",
        required=True,
    ),
)


async def run_setup(session: SetupSession) -> None:
    """Collect the connection settings for both initial setup and reconfiguration."""
    setup_data = dict(session.context.setup_data)
    errors: dict[str, str | SetupFlowError] | None = None
    while True:
        entries = [replace(entry, value=setup_data.get(entry.key, entry.value)) for entry in _ENTRIES]
        setup_data.update(await session.form(entries, step_id="user", errors=errors, last_step=True))
        endpoint = str(setup_data.get("endpoint") or "").strip()
        parsed = urlparse(endpoint)
        if parsed.scheme not in {"ws", "wss"} or not parsed.hostname or parsed.path != "/connect":
            errors = {"endpoint": "Enter a reachable ws:// or wss:// URL ending in /connect."}
            continue
        try:
            await session.finish(setup_data)
            return
        except SetupFlowError as err:
            errors = {"base": err}
