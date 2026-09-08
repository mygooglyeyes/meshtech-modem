#!/usr/bin/env python3
"""meshtech-modem - emulate an openHop pymc_tcp modem.

openHop Repeater connects to this program's TCP port believing it is a
dedicated LoRa modem (radio_type: pymc_tcp).  We speak the exact wire
protocol its driver expects (see PROTOCOL.md) and broadcast every
packet the MeshTech bot's MCP module feeds us - both packets the radio
hears over the air AND packets the bot transmits (a radio never hears
itself, so those are looped back explicitly).

This first version needs no radio: the RX feed is a queue that the
MCP module (or any test harness) pushes into.  Wiring it to the real
MCP feed is the next step after the MCP exists.
"""
from __future__ import annotations

import asyncio
import hmac
import logging
import struct
import time
from typing import Optional

log = logging.getLogger("meshtech-modem")

# ─── Wire protocol (mirrors openhop-core protocol_constants.py) ──────
# Keep in sync with PROTOCOL.md and the openhop-core / firmware sources.

PROTO_SYNC = 0xAA
MAX_LORA_PAYLOAD = 255

# Host → modem
CMD_TX_REQUEST = 0x01
CMD_SET_CONFIG = 0x10
CMD_GET_CONFIG = 0x11
CMD_STATUS_REQ = 0x20
CMD_NOISE_REQ = 0x22
CMD_CAD_REQUEST = 0x30
CMD_RX_START = 0x31
CMD_SET_CAD_PARAMS = 0x34
CMD_AUTH = 0x50
CMD_GET_VERSION = 0x70
CMD_PING = 0xFF

# Modem → host
CMD_TX_DONE = 0x02
CMD_TX_FAIL = 0x03
CMD_RX_PACKET = 0x04
CMD_CONFIG_RESP = 0x12
CMD_STATUS_RESP = 0x21
CMD_NOISE_RESP = 0x23
CMD_CAD_RESP = 0x32
CMD_RX_STARTED = 0x33
CMD_CAD_PARAMS_RESP = 0x35
CMD_AUTH_OK = 0x51
CMD_VERSION_RESP = 0x71
CMD_ERROR = 0xFE
CMD_PONG = 0xFF

# Error codes (CMD_ERROR payload[0])
ERR_CRC_MISMATCH = 0x01
ERR_INVALID_CMD = 0x02
ERR_RADIO_BUSY = 0x03
ERR_PAYLOAD_TOO_BIG = 0x05
ERR_UNAUTHORIZED = 0x09

RADIO_CONFIG_FMT = "<IIBBbHB"       # freq, bw, sf, cr, power, syncword, preamble
RADIO_CONFIG_SIZE = struct.calcsize(RADIO_CONFIG_FMT)   # 14
STATUS_RESP_FMT = "<IIIIhhhbB"      # uptime, rx, tx, crc_err, rssi, snr, noise, temp, state
STATUS_RESP_SIZE = struct.calcsize(STATUS_RESP_FMT)     # 24

FRAME_HEADER = struct.Struct("<BH")  # CMD, LEN (both after SYNC byte)


def crc16_ccitt(data: bytes) -> int:
    """CRC-16/CCITT-FALSE: poly 0x1021, init 0xFFFF, no reflect, no xor-out."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = (crc << 1) ^ 0x1021
            else:
                crc <<= 1
            crc &= 0xFFFF
    return crc


def build_frame(cmd: int, payload: bytes = b"") -> bytes:
    """SYNC | CMD | LEN(LE) | PAYLOAD | CRC16(LE, over CMD+LEN+PAYLOAD)."""
    if len(payload) > 0xFFFF:
        raise ValueError("payload exceeds 16-bit LEN field")
    hdr = FRAME_HEADER.pack(cmd, len(payload))
    return bytes([PROTO_SYNC]) + hdr + payload + struct.pack("<H", crc16_ccitt(hdr + payload))


def parse_frame(buf: bytes) -> Optional[tuple[int, bytes, int]]:
    """Parse the first complete frame in buf.

    Returns (cmd, payload, total_frame_size) or None if incomplete.
    Raises ValueError on a CRC mismatch (caller should answer with
    ERR_CRC_MISMATCH and resynchronise).
    """
    sync_idx = buf.find(bytes([PROTO_SYNC]))
    if sync_idx < 0:
        return None
    if len(buf) < sync_idx + 4:
        return None
    off = sync_idx
    cmd = buf[off + 1]
    (length,) = struct.unpack_from("<H", buf, off + 2)
    total = 4 + length + 2
    if len(buf) < off + total:
        return None
    payload = buf[off + 4:off + 4 + length]
    (crc,) = struct.unpack_from("<H", buf, off + 4 + length)
    hdr = FRAME_HEADER.pack(cmd, length)
    if crc16_ccitt(hdr + payload) != crc:
        raise ValueError("CRC mismatch")
    return cmd, payload, off + total


def build_rx_packet(rssi: int, snr: float, signal_rssi: int, data: bytes) -> bytes:
    """Wrap raw LoRa bytes in an RX_PACKET frame with radio metadata."""
    if len(data) > MAX_LORA_PAYLOAD:
        raise ValueError("LoRa payload too big")
    meta = struct.pack("<hhh", int(rssi), int(round(snr * 10)), int(signal_rssi))
    return build_frame(CMD_RX_PACKET, meta + data)


class ModemClient:
    """One connected openHop driver."""

    def __init__(self, reader: asyncio.StreamReader,
                 writer: asyncio.StreamWriter, modem: "ModemServer"):
        self.reader = reader
        self.writer = writer
        self.modem = modem
        self.authenticated = modem.token == ""
        self.rx_enabled = True

    async def send_frame(self, cmd: int, payload: bytes = b"") -> None:
        self.writer.write(build_frame(cmd, payload))
        await self.writer.drain()

    async def broadcast_rx(self, rssi: int, snr: float,
                           signal_rssi: int, data: bytes) -> None:
        if not self.rx_enabled:
            return
        self.writer.write(build_rx_packet(rssi, snr, signal_rssi, data))
        await self.writer.drain()

    async def run(self) -> None:
        """Serve one client until it disconnects."""
        buf = b""
        try:
            while True:
                chunk = await self.reader.read(4096)
                if not chunk:
                    break
                buf += chunk
                # Memory guard: a client that never completes a frame (or
                # floods SYNC-less garbage) must not grow the buffer
                # without bound. 64 KB is far above any legitimate frame
                # (max 261 B); beyond it we drop the buffer entirely.
                if len(buf) > 65536:
                    log.warning("Input buffer overflow - dropping %d bytes", len(buf))
                    buf = b""
                # Resynchronise on garbage: drop bytes before the first SYNC.
                idx = buf.find(bytes([PROTO_SYNC]))
                if idx > 0:
                    buf = buf[idx:]
                while True:
                    try:
                        parsed = parse_frame(buf)
                    except ValueError:
                        log.warning("CRC mismatch - answering with error, resync")
                        await self.send_frame(CMD_ERROR, bytes([ERR_CRC_MISMATCH]))
                        idx = buf.find(bytes([PROTO_SYNC]), 1)
                        buf = buf[idx:] if idx >= 0 else b""
                        continue
                    if parsed is None:
                        break
                    cmd, payload, size = parsed
                    buf = buf[size:]
                    if not await self.handle(cmd, payload):
                        return
        except (ConnectionResetError, BrokenPipeError):
            pass
        finally:
            log.info("Client disconnected")

    async def handle(self, cmd: int, payload: bytes) -> bool:
        """Handle one host command. Returns False to close the connection."""
        if not self.authenticated and cmd != CMD_AUTH:
            await self.send_frame(CMD_ERROR, bytes([ERR_UNAUTHORIZED]))
            return False

        if cmd == CMD_AUTH:
            # hmac.compare_digest is constant-time: no token-length or
            # prefix-match side channel.
            supplied = payload.decode("utf-8", "replace")
            if (not self.modem.token
                    or not hmac.compare_digest(supplied, self.modem.token)):
                log.warning("Auth rejected")
                await self.send_frame(CMD_ERROR, bytes([ERR_UNAUTHORIZED]))
                return False
            self.authenticated = True
            log.info("Auth accepted")
            await self.send_frame(CMD_AUTH_OK)
            return True

        if cmd == CMD_PING:
            await self.send_frame(CMD_PONG)
            return True

        if cmd in (CMD_SET_CONFIG, CMD_GET_CONFIG):
            if cmd == CMD_SET_CONFIG:
                if len(payload) != RADIO_CONFIG_SIZE:
                    await self.send_frame(CMD_ERROR, bytes([ERR_PAYLOAD_TOO_BIG]))
                    return True
                self.modem.config = payload
                log.info("Radio configured: %s", _describe_config(payload))
            await self.send_frame(CMD_CONFIG_RESP, self.modem.config)
            return True

        if cmd == CMD_CAD_REQUEST:
            # The MCP is the real LBT brain; the modem just reports.
            busy = 1 if self.modem.channel_busy() else 0
            await self.send_frame(CMD_CAD_RESP, bytes([busy]))
            return True

        if cmd == CMD_TX_REQUEST:
            await self.modem.handle_tx_request(self, payload)
            return True

        if cmd == CMD_RX_START:
            self.rx_enabled = True
            await self.send_frame(CMD_RX_STARTED)
            return True

        if cmd == CMD_SET_CAD_PARAMS:
            await self.send_frame(CMD_CAD_PARAMS_RESP, payload)
            return True

        if cmd == CMD_STATUS_REQ:
            status = struct.pack(
                STATUS_RESP_FMT,
                int(time.time() - self.modem.started),
                self.modem.rx_count, self.modem.tx_count, 0,
                -100, 0, -1050, 40, 1,
            )
            await self.send_frame(CMD_STATUS_RESP, status)
            return True

        if cmd == CMD_NOISE_REQ:
            await self.send_frame(CMD_NOISE_RESP, struct.pack("<h", -1050))
            return True

        if cmd == CMD_GET_VERSION:
            await self.send_frame(CMD_VERSION_RESP, bytes([1, 0]))
            return True

        log.warning("Unknown command 0x%02X", cmd)
        await self.send_frame(CMD_ERROR, bytes([ERR_INVALID_CMD]))
        return True


def _describe_config(payload: bytes) -> str:
    freq, bw, sf, cr, power, syncword, preamble = struct.unpack(RADIO_CONFIG_FMT, payload)
    return (f"{freq / 1e6:.3f}MHz BW{bw / 1000:.0f}kHz SF{sf} CR{cr} "
            f"{power}dBm sync=0x{syncword:04X} pre={preamble}")


class ModemServer:
    """Accepts openHop connections and broadcasts the MCP feed."""

    def __init__(self, host: str = "127.0.0.1", port: int = 5055,
                 token: str = "", rx_feed: Optional[asyncio.Queue] = None):
        self.host = host
        self.port = port
        self.token = token
        self.rx_feed = rx_feed  # (rssi, snr, signal_rssi, data) tuples
        self.config = struct.pack(RADIO_CONFIG_FMT, 910525000, 62500, 7, 5, 22, 0x12, 17)
        self.started = time.time()
        self.rx_count = 0
        self.tx_count = 0
        self.clients: list[ModemClient] = []
        self._busy = False

    def channel_busy(self) -> bool:
        """Honest CAD answer. The MCP sets this during real transmissions."""
        return self._busy

    def set_busy(self, busy: bool) -> None:
        self._busy = busy

    async def handle_tx_request(self, client: ModemClient, data: bytes) -> None:
        """Answer TX honestly: the real radio lives in the MCP module.

        No MCP feed attached yet -> TX_FAIL, exactly like a real modem
        whose radio did not assert TX_DONE.
        """
        if not data or len(data) > MAX_LORA_PAYLOAD:
            await client.send_frame(CMD_ERROR, bytes([ERR_PAYLOAD_TOO_BIG]))
            return
        if self.rx_feed is None:
            log.info("TX_REQUEST (%dB) but no radio feed attached - TX_FAIL", len(data))
            await client.send_frame(CMD_TX_FAIL)
            return
        # Real feed path: the bytes go out over the air via the MCP, the
        # transmitted packet loops back into the RX broadcast (the radio
        # cannot hear itself), and TX_DONE confirms to the host.
        self.tx_count += 1
        self.rx_feed.put_nowait((-100, 0.0, -100, data))   # TX loopback
        await client.send_frame(CMD_TX_DONE, struct.pack("<I", 0))

    async def feed_pump(self) -> None:
        """Broadcast everything that arrives on the RX feed to all clients."""
        while True:
            rssi, snr, signal_rssi, data = await self.rx_feed.get()
            self.rx_count += 1
            for client in list(self.clients):
                try:
                    await client.broadcast_rx(rssi, snr, signal_rssi, data)
                except (ConnectionResetError, BrokenPipeError):
                    pass

    async def _handle_client(self, reader: asyncio.StreamReader,
                             writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("peername")
        log.info("Client connected from %s", peer)
        client = ModemClient(reader, writer, self)
        self.clients.append(client)
        try:
            await client.run()
        finally:
            if client in self.clients:
                self.clients.remove(client)
            writer.close()
            try:
                await writer.wait_closed()
            except (ConnectionResetError, BrokenPipeError):
                pass

    async def serve(self) -> None:
        server = await asyncio.start_server(self._handle_client, self.host, self.port)
        log.info("meshtech-modem listening on %s:%d (token %s)",
                 self.host, self.port, "set" if self.token else "open")
        pump = asyncio.create_task(self.feed_pump())
        async with server:
            try:
                await server.serve_forever()
            finally:
                pump.cancel()


def load_config(path: str) -> dict:
    """Read a simple key = value config file (no dependencies).

    Supported keys: host, port, token. Blank lines and # comments are
    ignored. Values keep internal whitespace; keys are case-insensitive.
    Missing file -> empty dict (defaults apply).
    """
    cfg: dict[str, str] = {}
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                cfg[key.strip().lower()] = value.strip()
    except FileNotFoundError:
        log.warning("Config file %s not found - using defaults", path)
    return cfg


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="openHop pymc_tcp modem emulator")
    parser.add_argument("--config", default="modem.conf",
                        help="config file (default: modem.conf)")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--token", default=None)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    # Precedence: command line > config file > built-in defaults.
    cfg = load_config(args.config)
    host = args.host if args.host is not None else cfg.get("host", "127.0.0.1")
    port = args.port if args.port is not None else int(cfg.get("port", "5055"))
    token = args.token if args.token is not None else cfg.get("token", "")

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    modem = ModemServer(host=host, port=port, token=token,
                        rx_feed=asyncio.Queue(maxsize=1000))
    try:
        asyncio.run(modem.serve())
    except KeyboardInterrupt:
        log.info("Stopped")


if __name__ == "__main__":
    main()
