"""Metrolist Device Connect v2 transport and pairing session."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import os
import struct
import time
import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

import aiohttp
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from .account import derive_account_identity

VERSION = 2
LABEL = b"metrolist-device-connect-v2"
CHUNK_SIZE = 24 * 1024
MAX_PLAYBACK_BYTES = 8 * 1024 * 1024


def b64(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def unb64(value: str) -> bytes:
    return base64.b64decode(value, validate=True)


def lp(*parts: bytes) -> bytes:
    return b"".join(struct.pack(">I", len(p)) + p for p in parts)


def proof(secret: bytes, phase: str, role: str, sender: str, receiver: str, transcript: bytes) -> str:
    data = lp(LABEL, phase.encode(), role.encode(), sender.encode(), receiver.encode(), transcript)
    return b64(hmac.new(secret, data, hashlib.sha256).digest())


def hkdf(secret: bytes, salt: bytes, info: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=salt, info=info).derive(secret)


def _commitment(role: str, device_id: str, nonce: bytes, pub: bytes) -> bytes:
    return hashlib.sha256(lp(LABEL + b"/hello-commit", struct.pack(">I", VERSION), role.encode(), device_id.encode(), nonce, pub)).digest()


def _transcript(local: dict[str, Any], peer: dict[str, Any], local_commit: bytes, peer_commit: bytes) -> bytes:
    initiator, responder = (local, peer) if local["role"] == "initiator" else (peer, local)
    initiator_commit, responder_commit = (local_commit, peer_commit) if local["role"] == "initiator" else (peer_commit, local_commit)
    return hashlib.sha256(lp(LABEL, struct.pack(">I", VERSION), initiator_commit, responder_commit,
        initiator["role"].encode(), initiator["deviceId"].encode(), unb64(initiator["nonce"]), unb64(initiator["publicKey"]),
        responder["role"].encode(), responder["deviceId"].encode(), unb64(responder["nonce"]), unb64(responder["publicKey"]))).digest()


def _aad(kind: str, seq: int) -> bytes:
    return f"metrolist-device-connect-v2:{kind}:{seq}".encode()


@dataclass
class DeviceConnectSession:
    url: str
    device_id: str
    device_name: str
    cookie: str
    data_sync_id: str
    peer_id: str
    pair_secret: str
    save_pair: Callable[[str, str], None]
    logger: logging.Logger
    on_playback: Callable[[dict[str, Any]], None]

    def __post_init__(self) -> None:
        self.ws: aiohttp.ClientWebSocketResponse | None = None
        self.http: aiohttp.ClientSession | None = None
        self.send_seq = 0
        self.recv_seq = 0
        self.connected = False
        self.stage = "opening WebSocket"
        self.peer_name = "Metrolist"
        self.peer_model = ""
        self.session_id = str(uuid.uuid4())
        self.revision = 0
        self.queue_revision = 0
        self._send_lock = asyncio.Lock()
        self._pair_chunks: dict[str, Any] = {}
        self.expected_peer_id = self.peer_id
        self.pair_secret_bytes = unb64(self.pair_secret) if self.pair_secret else b""

    async def connect(self) -> None:
        self.stage = "opening WebSocket"
        self.http = aiohttp.ClientSession()
        self.ws = await asyncio.wait_for(self.http.ws_connect(self.url, heartbeat=20, max_msg_size=MAX_PLAYBACK_BYTES + 65536), 10)
        self.stage = "creating handshake"
        local_key = ec.generate_private_key(ec.SECP256R1())
        local_pub = local_key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
        local = {"version": VERSION, "role": "initiator", "deviceId": self.device_id, "nonce": b64(os.urandom(16)), "publicKey": b64(local_pub)}
        local_commit = _commitment(local["role"], self.device_id, unb64(local["nonce"]), local_pub)
        self.stage = "sending handshake"
        await self._clear_send("hello_commit", {"version": VERSION, "role": "initiator", "deviceId": self.device_id, "commitment": b64(local_commit)})
        await self._clear_send("hello", local)
        self.stage = "waiting for peer handshake"
        peer_commit_wire = await self._receive_clear("hello_commit")
        peer_commit_data = peer_commit_wire["payload"]
        peer_commit = unb64(peer_commit_data["commitment"])
        if len(peer_commit) != 32 or peer_commit_data.get("version") != VERSION or peer_commit_data.get("role") != "responder":
            raise RuntimeError("Metrolist sent an invalid handshake commitment")
        peer = await self._receive_clear("hello")
        if peer.get("version") != VERSION or peer.get("role") != "responder" or peer.get("deviceId") == self.device_id:
            raise RuntimeError("Metrolist sent an invalid handshake")
        peer_pub_der = unb64(peer["publicKey"])
        if not hmac.compare_digest(peer_commit, _commitment("responder", peer["deviceId"], unb64(peer["nonce"]), peer_pub_der)):
            raise RuntimeError("Metrolist handshake commitment did not match")
        self.stage = "validating peer handshake"
        shared = local_key.exchange(ec.ECDH(), serialization.load_der_public_key(peer_pub_der))
        transcript = _transcript(local, peer, local_commit, peer_commit)
        self._out_key = hkdf(shared, transcript, LABEL + b"/initiator")
        self._in_key = hkdf(shared, transcript, LABEL + b"/responder")
        self.peer_id = peer["deviceId"]
        if self.expected_peer_id and self.peer_id != self.expected_peer_id:
            raise RuntimeError("Connected Metrolist device does not match the configured peer")
        fp, account_proof = derive_account_identity(self.cookie, self.data_sync_id)
        self.account_fingerprint, self.account_proof = fp, account_proof
        local_identity = {"fingerprint": fp, "accountProof": "", "anonymous": False, "resolved": True,
                          "hasPair": bool(self.pair_secret), "supportsCodePairing": True}
        self.local_identity = local_identity
        self.peer_identity = None
        self._hello_transcript = transcript
        self._pair_secret = hkdf(shared, transcript, LABEL + b"/pair-secret")
        self.stage = "sending account identity"
        await self.send("identity", local_identity)
        self.stage = "waiting for peer identity/pairing response"
        while not self.connected:
            self.stage = "waiting for peer identity/pairing response"
            await self._handle(await self._recv())

    async def run(self) -> None:
        try:
            while self.ws and not self.ws.closed:
                await self._handle(await self._recv())
        finally:
            self.connected = False

    async def close(self) -> None:
        self.connected = False
        if self.ws:
            await self.ws.close()
        if self.http:
            await self.http.close()

    async def _clear_send(self, kind: str, payload: dict[str, Any]) -> None:
        assert self.ws
        await self.ws.send_str(json.dumps({"type": kind, "payload": json.dumps(payload, separators=(",", ":")), "version": VERSION, "encrypted": False, "seq": 0}, separators=(",", ":")))

    async def _receive_clear(self, expected: str) -> dict[str, Any]:
        wire = json.loads(await asyncio.wait_for(self.ws.receive_str(), 10))
        if wire.get("type") != expected or wire.get("encrypted") or wire.get("seq") != 0:
            raise RuntimeError("Metrolist sent an invalid handshake frame")
        return json.loads(wire["payload"])

    async def send(self, kind: str, payload: dict[str, Any]) -> None:
        assert self.ws
        raw = json.dumps(payload, separators=(",", ":")).encode()
        async with self._send_lock:
            self.send_seq += 1
            seq = self.send_seq
            nonce = os.urandom(12)
            encrypted = nonce + AESGCM(self._out_key).encrypt(nonce, raw, _aad(kind, seq))
            wire = {"type": kind, "payload": b64(encrypted), "version": VERSION, "encrypted": True, "seq": seq}
            await self.ws.send_str(json.dumps(wire, separators=(",", ":")))

    async def _recv(self) -> dict[str, Any]:
        assert self.ws
        msg = await self.ws.receive(timeout=310)
        if msg.type != aiohttp.WSMsgType.TEXT:
            raise RuntimeError("Metrolist WebSocket disconnected")
        wire = json.loads(msg.data)
        if wire.get("version") != VERSION or not wire.get("encrypted"):
            raise RuntimeError("Metrolist sent an invalid encrypted frame")
        seq = int(wire.get("seq", 0))
        if seq <= self.recv_seq:
            raise RuntimeError("Metrolist sent a replayed frame")
        data = unb64(wire["payload"])
        if len(data) < 28:
            raise RuntimeError("Metrolist sent a truncated encrypted frame")
        clear = AESGCM(self._in_key).decrypt(data[:12], data[12:], _aad(wire["type"], seq))
        self.recv_seq = seq
        return {"type": wire["type"], "payload": json.loads(clear)}

    async def _handle(self, frame: dict[str, Any]) -> None:
        kind, payload = frame["type"], frame["payload"]
        self.stage = f"processing peer {kind}"
        if kind == "identity":
            if payload.get("anonymous") or payload.get("fingerprint") != self.account_fingerprint or not payload.get("resolved"):
                raise RuntimeError("Metrolist account identity does not match the configured account")
            self.peer_identity = payload
            local_meta = lp(self.account_fingerprint.encode(), bytes([0, 1, int(bool(self.local_identity["hasPair"])), 1]))
            peer_meta = lp(payload.get("fingerprint", "").encode(), bytes([0, 1, int(bool(payload.get("hasPair"))), 1]))
            code_transcript = hashlib.sha256(lp(LABEL + b"/mutual-code-pairing", self._hello_transcript, local_meta, peer_meta)).digest()
            if payload.get("supportsCodePairing"):
                self._code_transcript = code_transcript
                self._pair_secret = hkdf(self._pair_secret, code_transcript, LABEL + b"/pair-secret")
                self.pair_secret_bytes = unb64(self.pair_secret) if self.pair_secret else self._pair_secret
            if self.local_identity["hasPair"] and payload.get("hasPair"):
                await self._send_proof("pair_proof", "reconnect")
            else:
                await self._send_proof("pair_request", "pair-request")
                sas_hash = hmac.new(self._pair_secret, LABEL + b"/sas", hashlib.sha256).digest()
                code = int.from_bytes(sas_hash[:4], "big") % 1_000_000
                self.logger.warning("Device Connect pairing code: %06d. Compare it with Metrolist and approve that same code on the device.", code)
                await self._send_proof("pair_approve", "pair-approve")
        elif kind == "pair_proof":
            if not self._check_proof(payload, "reconnect"):
                raise RuntimeError("Saved Device Connect pairing was rejected")
            self.connected = True
            await self._local_info()
        elif kind == "pair_request":
            if not self._check_proof(payload, "pair-request"):
                raise RuntimeError("Invalid Device Connect pairing request")
        elif kind == "pair_approve":
            if not self._check_proof(payload, "pair-approve"):
                raise RuntimeError("Invalid Device Connect pairing approval")
            await self._persist_pair()
            await self._send_proof("pair_commit", "pair-commit")
            self.connected = True
            await self._local_info()
        elif kind == "pair_commit":
            if not self._check_proof(payload, "pair-commit"):
                raise RuntimeError("Invalid Device Connect pairing commit")
            await self._persist_pair()
            self.connected = True
            await self._local_info()
        elif kind == "auth_result" and not payload.get("accepted"):
            raise RuntimeError("Metrolist rejected Device Connect authentication")
        elif kind == "device_info":
            if payload.get("deviceId") != self.peer_id:
                raise RuntimeError("Metrolist device information did not match the paired peer")
            self.peer_name = payload.get("deviceName") or self.peer_name
            self.peer_model = payload.get("model") or ""
        elif kind == "playback":
            await self._playback_chunk(payload)
        elif kind == "ping":
            await self.send("pong", {"t": payload.get("t", 0)})
        elif kind == "bye":
            raise RuntimeError("Metrolist closed the Device Connect session")

    async def _send_proof(self, kind: str, phase: str) -> None:
        await self.send(kind, {"deviceId": self.device_id, "proof": proof(self.pair_secret_bytes, phase,
            "initiator", self.device_id, self.peer_id, self.transcript_hash)})

    def _check_proof(self, payload: dict[str, Any], phase: str) -> bool:
        if payload.get("deviceId") != self.peer_id:
            return False
        expected = proof(self.pair_secret_bytes, phase, "responder", self.peer_id, self.device_id, self.transcript_hash)
        return hmac.compare_digest(str(payload.get("proof", "")), expected)

    @property
    def transcript_hash(self) -> bytes:
        return getattr(self, "_code_transcript", self._hello_transcript)

    async def _persist_pair(self) -> None:
        secret = b64(self._pair_secret)
        self.save_pair(self.peer_id, secret)
        self.pair_secret = secret

    async def _local_info(self) -> None:
        await self.send("device_info", {"deviceId": self.device_id, "deviceName": self.device_name,
            "model": "Music Assistant", "playbackVersion": 4, "supportsPlaybackClock": True,
            "supportsPlaybackPitch": False, "deviceType": "desktop"})
        await self.send_playback({"type": "ATTACH", "auto": True})

    async def _playback_chunk(self, chunk: dict[str, Any]) -> None:
        mid = chunk.get("messageId")
        count, idx, total = int(chunk.get("count", 0)), int(chunk.get("index", -1)), int(chunk.get("totalBytes", 0))
        if not mid or not 0 < total <= MAX_PLAYBACK_BYTES or not 0 < count <= 350 or idx < 0 or idx >= count:
            raise RuntimeError("Invalid Metrolist playback chunk")
        if idx == 0:
            self._pair_chunks[mid] = [count, total, []]
        state = self._pair_chunks.get(mid)
        if not state or idx != len(state[2]) or state[:2] != [count, total]:
            self._pair_chunks.clear()
            raise RuntimeError("Out of order Metrolist playback chunks")
        state[2].append(unb64(chunk.get("data", "")))
        if idx + 1 == count:
            data = b"".join(state[2])
            del self._pair_chunks[mid]
            if len(data) != total:
                raise RuntimeError("Invalid Metrolist playback message length")
            self.on_playback(json.loads(data))

    async def send_playback(self, message: dict[str, Any]) -> None:
        encoded = json.dumps(message, separators=(",", ":")).encode()
        if not encoded or len(encoded) > MAX_PLAYBACK_BYTES:
            raise ValueError("Playback transfer is too large")
        mid = b64(os.urandom(16))
        chunks = [encoded[i:i + CHUNK_SIZE] for i in range(0, len(encoded), CHUNK_SIZE)]
        for index, data in enumerate(chunks):
            await self.send("playback", {"messageId": mid, "index": index, "count": len(chunks),
                "totalBytes": len(encoded), "data": b64(data)})
