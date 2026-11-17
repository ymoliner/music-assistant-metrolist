"""Small protobuf wire codec and Metro Server host connection."""

from __future__ import annotations

import asyncio
import gzip
import logging
import struct
import time
from dataclasses import dataclass
from typing import Any

import aiohttp


def _varint(value: int) -> bytes:
    value = max(0, int(value))
    out = bytearray()
    while value > 0x7F:
        out.append((value & 0x7F) | 0x80)
        value >>= 7
    out.append(value)
    return bytes(out)


def _read_varint(data: bytes, offset: int) -> tuple[int, int]:
    value = shift = 0
    while offset < len(data):
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if byte < 0x80:
            return value, offset
        shift += 7
        if shift > 63:
            raise ValueError("Invalid protobuf varint")
    raise ValueError("Truncated protobuf varint")


def _fields(data: bytes) -> dict[int, list[tuple[int, Any]]]:
    result: dict[int, list[tuple[int, Any]]] = {}
    offset = 0
    while offset < len(data):
        key, offset = _read_varint(data, offset)
        number, wire = key >> 3, key & 7
        if wire == 0:
            value, offset = _read_varint(data, offset)
        elif wire == 1:
            value, offset = data[offset : offset + 8], offset + 8
        elif wire == 2:
            size, offset = _read_varint(data, offset)
            value, offset = data[offset : offset + size], offset + size
        elif wire == 5:
            value, offset = data[offset : offset + 4], offset + 4
        else:
            raise ValueError(f"Unsupported protobuf wire type {wire}")
        result.setdefault(number, []).append((wire, value))
    return result


def _put(number: int, wire: int, value: bytes | int) -> bytes:
    key = _varint((number << 3) | wire)
    if wire == 0:
        return key + _varint(int(value))
    raw = value if isinstance(value, bytes) else b""
    if wire == 2:
        return key + _varint(len(raw)) + raw
    return key + raw


def _str(number: int, value: str | None) -> bytes:
    return _put(number, 2, (value or "").encode()) if value else b""


def _int(number: int, value: int) -> bytes:
    return _put(number, 0, value) if value else b""


def _track(track: dict[str, Any]) -> bytes:
    return b"".join(
        (
            _str(1, track.get("id")),
            _str(2, track.get("title")),
            _str(3, track.get("artist")),
            _str(4, track.get("album")),
            _int(5, track.get("duration", 0)),
            _str(6, track.get("thumbnail")),
        )
    )


def encode_message(kind: str, payload: bytes = b"", request_id: int = 0) -> bytes:
    envelope = _str(1, kind) + (_put(2, 2, payload) if payload else b"") + _int(4, request_id)
    return envelope


def decode_message(data: bytes) -> tuple[str, dict[int, list[tuple[int, Any]]]]:
    envelope = _fields(data)
    kind = envelope.get(1, [(2, b"")])[0][1].decode()
    payload = envelope.get(2, [(2, b"")])[0][1]
    compressed = bool(envelope.get(3, [(0, 0)])[0][1])
    if compressed:
        payload = gzip.decompress(payload)
    return kind, _fields(payload)


def create_payload(username: str) -> bytes:
    return _str(1, username)


def capabilities_payload() -> bytes:
    fields = _put(1, 0, 1) + _str(3, "ma-metrolist-bridge/0.1")
    for feature in (
        "request_id",
        "origin_tag",
        "drift_report",
        "desync_canary",
        "server_restarting",
        "replace_queue",
        "host_sequence",
        "track_revision",
    ):
        fields += _put(4, 2, feature.encode())
    return fields


def action_payload(
    action: str,
    track: dict[str, Any] | None = None,
    position: int = 0,
    queue: list[dict[str, Any]] | None = None,
    queue_title: str | None = None,
    revision: int = 0,
    host_sequence: int = 0,
) -> bytes:
    result = _str(1, action)
    if track:
        result += _str(2, track["id"])
        result += _put(4, 2, _track(track))
    for queue_track in queue or []:
        result += _put(6, 2, _track(queue_track))
    result += _str(7, queue_title)
    result += _int(3, position)
    result += _int(9, int(time.time() * 1000))
    result += _int(10, revision)
    result += _int(11, int(time.time() * 1000))
    if action == "change_track" and queue is not None:
        result += _put(12, 0, 1)
    result += _int(14, host_sequence)
    return result


def _one(fields: dict[int, list[tuple[int, Any]]], number: int, default: Any = None) -> Any:
    values = fields.get(number)
    return values[-1][1] if values else default


@dataclass
class MetroSession:
    """One host connection to a Metro Server room."""

    provider: Any
    url: str
    username: str

    def __post_init__(self) -> None:
        self.logger: logging.Logger = self.provider.logger.getChild("metro")
        self.http: aiohttp.ClientSession | None = None
        self.ws: aiohttp.ClientWebSocketResponse | None = None
        self.room_code: str | None = None
        self.session_token: str | None = None
        self.user_id: str | None = None
        self.compression = False
        self.sequence = 0
        self.host_sequence = 0
        self.revision = 0
        self.current_track: dict[str, Any] | None = None
        self.playing = False
        self.position = 0
        self.started_at = time.monotonic()

    async def connect_and_create(self) -> None:
        self.http = aiohttp.ClientSession()
        self.ws = await self.http.ws_connect(self.url, heartbeat=20, max_msg_size=2 * 1024 * 1024)
        await self.ws.send_bytes(encode_message("client_capabilities", capabilities_payload()))
        msg = await asyncio.wait_for(self.ws.receive(), timeout=8)
        if msg.type != aiohttp.WSMsgType.BINARY:
            raise RuntimeError("Metro Server did not negotiate its protobuf protocol")
        kind, fields = decode_message(msg.data)
        if kind != "server_capabilities" or not _one(fields, 1, 0):
            raise RuntimeError("Metro Server does not support protobuf clients")
        self.compression = bool(_one(fields, 2, 0))
        if not bool(_one(fields, 5, 0)):
            raise RuntimeError("This Metro Server does not allow this client to host rooms")
        await self._send("create_room", create_payload(self.username))
        while True:
            msg = await asyncio.wait_for(self.ws.receive(), timeout=10)
            if msg.type != aiohttp.WSMsgType.BINARY:
                raise RuntimeError("Metro Server closed before creating a room")
            kind, fields = decode_message(msg.data)
            if kind == "room_created":
                self.room_code = _one(fields, 1, b"").decode()
                self.user_id = _one(fields, 2, b"").decode()
                self.session_token = _one(fields, 3, b"").decode()
                break
            if kind == "error":
                raise RuntimeError(_one(fields, 2, b"Metro Server error").decode())
        if not self.room_code or not self.user_id or not self.session_token:
            raise RuntimeError("Metro Server returned an incomplete room session")
        self.logger.warning("Metrolist room created: %s (join from Metrolist Listen Together)", self.room_code)

    async def _send(self, kind: str, payload: bytes = b"") -> None:
        if not self.ws or self.ws.closed:
            raise RuntimeError("Metro Server connection is not available")
        self.sequence += 1
        await self.ws.send_bytes(encode_message(kind, payload, self.sequence))

    async def run(self) -> None:
        """Keep the room connection alive and log guest changes/errors."""
        assert self.ws
        async for msg in self.ws:
            if msg.type != aiohttp.WSMsgType.BINARY:
                continue
            try:
                kind, fields = decode_message(msg.data)
            except (ValueError, OSError):
                self.logger.warning("Ignoring malformed Metro Server message")
                continue
            if kind == "user_joined":
                self.logger.info("Metrolist guest joined: %s", _one(fields, 2, b"Guest").decode())
            elif kind == "user_left":
                self.logger.info("Metrolist guest left: %s", _one(fields, 2, b"Guest").decode())
            elif kind == "error":
                self.logger.warning("Metro Server: %s", _one(fields, 2, b"unknown error").decode())
        if self.provider.player:
            self.provider.player._attr_available = False
            self.provider.player.update_state()
            self.logger.error("Metro Server connection ended; reload this provider to create a new room")

    async def publish_track(
        self,
        track: dict[str, Any],
        queue: list[dict[str, Any]] | None = None,
        queue_title: str | None = None,
    ) -> None:
        self.current_track = track
        self.position = 0
        self.started_at = time.monotonic()
        self.playing = True
        self.revision += 1
        await self._host_action("change_track", track, queue=queue, queue_title=queue_title)
        await self._host_action("play", track)

    async def control(self, action: str, position: int | None = None) -> None:
        pos = self.position_ms if position is None else position
        await self._host_action(action, self.current_track, pos)
        if action == "pause":
            self.position = pos
            self.playing = False
        elif action == "play":
            self.position = pos
            self.started_at = time.monotonic()
            self.playing = True
        elif action == "seek":
            self.position = pos
            self.started_at = time.monotonic()

    async def _host_action(
        self,
        action: str,
        track: dict[str, Any] | None = None,
        position: int = 0,
        queue: list[dict[str, Any]] | None = None,
        queue_title: str | None = None,
    ) -> None:
        self.host_sequence += 1
        payload = action_payload(
            action,
            track,
            position,
            queue,
            queue_title,
            revision=self.revision,
            host_sequence=self.host_sequence,
        )
        await self._send("playback_action", payload)

    @property
    def position_ms(self) -> int:
        return self.position + (int((time.monotonic() - self.started_at) * 1000) if self.playing else 0)

    async def close(self) -> None:
        if self.ws and not self.ws.closed:
            try:
                await self._send("leave_room")
            except (RuntimeError, aiohttp.ClientError):
                pass
            await self.ws.close()
        if self.http:
            await self.http.close()
