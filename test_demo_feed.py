"""Tests for the demo feed (synthetic packet injection)."""
from __future__ import annotations

import modem  # noqa: E402


def test_make_demo_packet_shape():
    rssi, snr, sig, data = modem.make_demo_packet(1)
    assert -42 <= rssi <= -35
    assert snr == 9.5
    assert sig == -50
    assert data.startswith(b"\x01")
    assert b"DEMO test packet 1" in data


def test_make_demo_packet_counter_varies():
    _, _, _, first = modem.make_demo_packet(1)
    _, _, _, second = modem.make_demo_packet(2)
    assert first != second
    assert b"DEMO test packet 2" in second


def test_demo_loop_injects_packets():
    import asyncio

    async def run():
        feed: asyncio.Queue = asyncio.Queue(maxsize=10)
        server = modem.ModemServer(rx_feed=feed, demo_feed=True, demo_interval=0.05)
        task = asyncio.create_task(server.demo_loop())
        pkt = await asyncio.wait_for(feed.get(), timeout=2.0)
        task.cancel()
        return pkt

    rssi, snr, sig, data = asyncio.run(run())
    assert b"DEMO test packet" in data


def test_demo_loop_off_when_disabled():
    import asyncio

    async def run():
        feed: asyncio.Queue = asyncio.Queue(maxsize=10)
        server = modem.ModemServer(rx_feed=feed, demo_feed=False)
        task = asyncio.create_task(server.demo_loop())
        await asyncio.sleep(0.1)
        assert feed.empty()
        task.cancel()

    asyncio.run(run())
