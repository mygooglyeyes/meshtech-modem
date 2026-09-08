"""Tests for meshtech-modem's protocol layer (modem.py).

Run:  python -m pytest test_modem.py -q
"""
from __future__ import annotations

import asyncio
import struct
import sys

import pytest

sys.path.insert(0, ".")
import modem  # noqa: E402


# ── framing ──────────────────────────────────────────────────────────

def test_crc_reference_vectors():
    # CRC-16/CCITT-FALSE check value for "123456789" is 0x29B1.
    assert modem.crc16_ccitt(b"123456789") == 0x29B1
    assert modem.crc16_ccitt(b"") == 0xFFFF  # init value when empty


def test_build_frame_roundtrip():
    frame = modem.build_frame(0x10, b"\x01\x02\x03")
    assert frame[0] == modem.PROTO_SYNC
    cmd, payload, size = modem.parse_frame(frame)
    assert cmd == 0x10
    assert payload == b"\x01\x02\x03"
    assert size == len(frame)


def test_frame_empty_payload():
    frame = modem.build_frame(modem.CMD_PING)
    cmd, payload, size = modem.parse_frame(frame)
    assert cmd == modem.CMD_PING
    assert payload == b""
    assert size == len(frame)


def test_frame_crc_corruption_detected():
    frame = bytearray(modem.build_frame(0x10, b"hello"))
    frame[-1] ^= 0xFF  # flip a CRC byte
    with pytest.raises(ValueError):
        modem.parse_frame(bytes(frame))


def test_frame_incomplete_returns_none():
    frame = modem.build_frame(0x10, b"x" * 20)
    assert modem.parse_frame(frame[:5]) is None


def test_frame_sync_resync():
    # Garbage before the SYNC byte is skipped.
    frame = modem.build_frame(0x10, b"ok")
    cmd, payload, size = modem.parse_frame(b"\xff\xff\xee" + frame)
    assert cmd == 0x10 and payload == b"ok"


def test_rx_packet_layout():
    frame = modem.build_rx_packet(-77, 0.5, -80, b"payload!")
    cmd, payload, _ = modem.parse_frame(frame)
    assert cmd == modem.CMD_RX_PACKET
    rssi, snr_x10, sig = struct.unpack("<hhh", payload[:6])
    assert rssi == -77
    assert snr_x10 == 5
    assert sig == -80
    assert payload[6:] == b"payload!"


def test_rx_packet_rejects_oversize():
    with pytest.raises(ValueError):
        modem.build_rx_packet(-77, 0.0, -80, b"x" * 256)


# ── server behaviour over a real socket pair ─────────────────────────

@pytest.fixture
def server_pair():
    """A ModemServer wired to an in-memory duplex pipe (no sockets)."""
    modem.ModemServer  # import touch
    return None  # real tests use start_server on localhost below


async def _connect(server: modem.ModemServer):
    """Start the server on an ephemeral port, return (reader, writer, port)."""
    import socket
    srv = await asyncio.start_server(server._handle_client, "127.0.0.1", 0)
    port = srv.sockets[0].getsockname()[1]
    pump = asyncio.create_task(server.feed_pump())
    await asyncio.sleep(0)   # yield once so feed_pump starts waiting
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    return reader, writer, srv, pump


async def _read_frame(reader: asyncio.StreamReader, buf: bytes = b""):
    """Read one complete frame; returns (cmd, payload, size, leftover buf).

    The buffer is threaded through by the caller: both frames of a
    TX+loopback pair can arrive in one TCP segment, and discarding the
    leftover after the first frame would drop the second.
    """
    while True:
        parsed = modem.parse_frame(buf)
        if parsed:
            cmd, payload, size = parsed
            return cmd, payload, size, buf[size:]
        buf += await asyncio.wait_for(reader.read(256), timeout=2.0)


async def _send(writer: asyncio.StreamWriter, cmd: int, payload: bytes = b""):
    writer.write(modem.build_frame(cmd, payload))
    await writer.drain()


@pytest.mark.asyncio
async def test_handshake_ping_and_config():
    server = modem.ModemServer(token="")  # open auth
    reader, writer, srv, pump = await _connect(server)
    try:
        await _send(writer, modem.CMD_PING)
        cmd, payload, _, _ = await _read_frame(reader)
        assert cmd == modem.CMD_PONG

        cfg = struct.pack(modem.RADIO_CONFIG_FMT,
                          910525000, 62500, 7, 5, 22, 0x12, 17)
        await _send(writer, modem.CMD_SET_CONFIG, cfg)
        cmd, payload, _, _ = await _read_frame(reader)
        assert cmd == modem.CMD_CONFIG_RESP
        assert payload == cfg
    finally:
        writer.close()
        pump.cancel()


@pytest.mark.asyncio
async def test_auth_required_when_token_set():
    server = modem.ModemServer(token="sekrit")
    reader, writer, srv, pump = await _connect(server)
    try:
        # Any command before auth is refused.
        await _send(writer, modem.CMD_PING)
        cmd, payload, _, _ = await _read_frame(reader)
        assert cmd == modem.CMD_ERROR
        assert payload == bytes([modem.ERR_UNAUTHORIZED])
    finally:
        writer.close()
        pump.cancel()


@pytest.mark.asyncio
async def test_wrong_token_rejected_and_closed():
    server = modem.ModemServer(token="sekrit")
    reader, writer, srv, pump = await _connect(server)
    try:
        # Wrong token as the FIRST command: ERROR reply then the server
        # closes the connection. Both may arrive in one read; EOF is the
        # second read returning b"".
        await _send(writer, modem.CMD_AUTH, b"wrong")
        buf = b""
        saw_error = False
        closed = False
        for _ in range(3):
            try:
                chunk = await asyncio.wait_for(reader.read(256), timeout=2.0)
            except asyncio.TimeoutError:
                break
            if chunk == b"":
                closed = True
                break
            buf += chunk
            parsed = modem.parse_frame(buf)
            if parsed:
                cmd, payload, size = parsed
                if cmd == modem.CMD_ERROR:
                    saw_error = True
                buf = buf[size:]
        assert saw_error and closed
    finally:
        writer.close()
        pump.cancel()


@pytest.mark.asyncio
async def test_auth_then_ping():
    server = modem.ModemServer(token="sekrit")
    reader, writer, srv, pump = await _connect(server)
    try:
        await _send(writer, modem.CMD_AUTH, b"sekrit")
        cmd, _, _, _ = await _read_frame(reader)
        assert cmd == modem.CMD_AUTH_OK

        await _send(writer, modem.CMD_PING)
        cmd, _, _, _ = await _read_frame(reader)
        assert cmd == modem.CMD_PONG
    finally:
        writer.close()
        pump.cancel()


@pytest.mark.asyncio
async def test_rx_feed_broadcasts_to_client():
    feed: asyncio.Queue = asyncio.Queue(maxsize=10)
    server = modem.ModemServer(rx_feed=feed)
    reader, writer, srv, pump = await _connect(server)
    try:
        await feed.put((-77, 0.5, -80, b"from the air"))
        cmd, payload, _, _ = await _read_frame(reader)
        assert cmd == modem.CMD_RX_PACKET
        rssi, snr_x10, sig = struct.unpack("<hhh", payload[:6])
        assert (rssi, snr_x10, sig) == (-77, 5, -80)
        assert payload[6:] == b"from the air"
        assert server.rx_count == 1
    finally:
        writer.close()
        pump.cancel()


@pytest.mark.asyncio
async def test_tx_loopback_feeds_rx_broadcast():
    """TX with a feed attached: TX_DONE + the packet loops back as RX."""
    feed: asyncio.Queue = asyncio.Queue(maxsize=10)
    server = modem.ModemServer(rx_feed=feed)
    reader, writer, srv, pump = await _connect(server)
    try:
        await _send(writer, modem.CMD_TX_REQUEST, b"bot packet")
        buf = b""
        cmd, payload, _, buf = await _read_frame(reader, buf)
        assert cmd == modem.CMD_TX_DONE

        # The loopback arrives on the same connection (possibly in the
        # same TCP segment, so the buffer is threaded through).
        cmd, payload, _, buf = await _read_frame(reader, buf)
        assert cmd == modem.CMD_RX_PACKET
        assert payload[6:] == b"bot packet"
        assert server.tx_count == 1
        assert server.rx_count == 1
    finally:
        writer.close()
        pump.cancel()


@pytest.mark.asyncio
async def test_tx_without_feed_fails_honestly():
    server = modem.ModemServer(rx_feed=None)
    reader, writer, srv, pump = await _connect(server)
    try:
        await _send(writer, modem.CMD_TX_REQUEST, b"bot packet")
        cmd, _, _, _ = await _read_frame(reader)
        assert cmd == modem.CMD_TX_FAIL
    finally:
        writer.close()
        pump.cancel()


@pytest.mark.asyncio
async def test_tx_oversize_rejected():
    server = modem.ModemServer(rx_feed=asyncio.Queue(maxsize=10))
    reader, writer, srv, pump = await _connect(server)
    try:
        await _send(writer, modem.CMD_TX_REQUEST, b"x" * 256)
        cmd, payload, _, _ = await _read_frame(reader)
        assert cmd == modem.CMD_ERROR
        assert payload == bytes([modem.ERR_PAYLOAD_TOO_BIG])
    finally:
        writer.close()
        pump.cancel()
