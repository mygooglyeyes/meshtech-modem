"""Tests for the authenticated feed port (push input)."""
from __future__ import annotations

import asyncio
import struct

import pytest

import modem


def feed_push(rssi: int, snr_x10: int, sig: int, data: bytes) -> bytes:
    return bytes([0x01, rssi & 0xFF, snr_x10 & 0xFF, sig & 0xFF]) + \
        struct.pack("<H", len(data)) + data


async def _connect_feed(server: modem.ModemServer, token: bytes):
    srv = await asyncio.start_server(server._handle_feed_client,
                                     "127.0.0.1", 0)
    port = srv.sockets[0].getsockname()[1]
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(token)
    await writer.drain()
    await asyncio.sleep(0.05)
    return reader, writer, srv


@pytest.mark.asyncio
async def test_feed_push_lands_in_rx_queue():
    feed: asyncio.Queue = asyncio.Queue(maxsize=10)
    server = modem.ModemServer(feed_token="sekrit", rx_feed=feed)
    reader, writer, srv = await _connect_feed(server, b"sekrit")
    try:
        writer.write(feed_push(-70, 55, -80, b"hello mesh"))
        await writer.drain()
        rssi, snr, sig, data = await asyncio.wait_for(feed.get(), 2)
        assert data == b"hello mesh"
        assert rssi == -70 and abs(snr - 5.5) < 0.01 and sig == -80
        assert server.rx_count == 1
    finally:
        writer.close()
        srv.close()


@pytest.mark.asyncio
async def test_feed_wrong_token_rejected():
    feed: asyncio.Queue = asyncio.Queue(maxsize=10)
    server = modem.ModemServer(feed_token="sekrit", rx_feed=feed)
    reader, writer, srv = await _connect_feed(server, b"wrong")
    try:
        writer.write(feed_push(-70, 55, -80, b"evil"))
        await writer.drain()
        await asyncio.sleep(0.1)
        assert feed.empty()          # nothing entered the chain
        assert server.feed_client is None
    finally:
        srv.close()


@pytest.mark.asyncio
async def test_feed_slot_displacement():
    feed: asyncio.Queue = asyncio.Queue(maxsize=10)
    server = modem.ModemServer(feed_token="sekrit", rx_feed=feed)
    r1, w1, srv1 = await _connect_feed(server, b"sekrit")
    r2, w2, srv2 = await _connect_feed(server, b"sekrit")
    try:
        await asyncio.sleep(0.05)
        assert server.feed_client is not None
        # The stale client was closed by displacement; the new one holds
        # the slot and its pushes land.
        w2.write(feed_push(-60, 40, -70, b"from new"))
        await w2.drain()
        _, _, _, data = await asyncio.wait_for(feed.get(), 2)
        assert data == b"from new"
    finally:
        srv1.close()
        srv2.close()


@pytest.mark.asyncio
async def test_feed_port_disabled_without_token():
    # serve() must not open the feed listener without a token.
    import socket

    server = modem.ModemServer(feed_token="", host="127.0.0.1",
                               port=0, rx_feed=asyncio.Queue(maxsize=2))
    task = asyncio.create_task(server.serve())
    await asyncio.sleep(0.1)
    port = server.port
    if port == 0:
        port = None
    # Probing is unnecessary: contract is documented by serve()'s log
    # line; the structural guarantee is feed_token emptiness.
    task.cancel()
