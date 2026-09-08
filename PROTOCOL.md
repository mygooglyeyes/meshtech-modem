# The pymc_tcp Modem Protocol

What meshtech-modem speaks on its TCP port (default 5055), so openHop
Repeater believes it is talking to real modem hardware.

This protocol was decoded from openhop-core's `TCPLoRaRadio` driver
(`hardware/tcp_radio.py`, `hardware/protocol_constants.py`) and the
openhop_modem firmware (`main.cpp`, `tcp_server.cpp`,
`frame_parser.cpp`). The driver and firmware must match bit-for-bit;
so must we.

## Frame format (both directions)

```
+------+-----+------+---------+--------+
| SYNC | CMD | LEN  | PAYLOAD | CRC16  |
| 0xAA | 1B  | 2B   | 0..255B | 2B LE  |
+------+-----+------+---------+--------+
```

- **LEN** is little-endian, covers PAYLOAD only.
- **CRC-16/CCITT-FALSE** (poly 0x1021, init 0xFFFF, no reflect, no
  xor-out) computed over CMD + LEN + PAYLOAD. The SYNC byte is
  excluded.
- PAYLOAD is capped at 255 bytes (the MeshCore radio MTU). Frames
  larger than that are rejected with `ERR_PAYLOAD_TOO_BIG`.

## Session handshake

What openHop's driver sends when it connects:

1. `AUTH` (0x50) with the token as payload - only if a token is
   configured. Answer `AUTH_OK` (0x51), or `ERROR` (0xFE) with
   `ERR_UNAUTHORIZED` (0x09).
2. `PING` (0xFF) - answer `PONG` (0xFF).
3. `SET_CONFIG` (0x10) with a 14-byte radio config - answer
   `CONFIG_RESP` (0x12) echoing the config.

If the connection drops, the driver reconnects with exponential
backoff and repeats the handshake, so the modem can start any time.

## Radio config (SET_CONFIG / CONFIG_RESP payload)

14 bytes, little-endian: `<IIBBbHB>`

| Field | Size | Meaning |
|---|---|---|
| frequency | u32 | Hz (e.g. 910525000) |
| bandwidth | u32 | Hz (e.g. 62500) |
| sf | u8 | spreading factor 7-12 |
| cr | u8 | coding rate 5-8 |
| power_dbm | i8 | TX power |
| syncword | u16 | (MeshCore default 0x12 low byte in use) |
| preamble | u8 | preamble length |

## Commands

| Code | Name | Host sends | Modem answers |
|---|---|---|---|
| 0x01 | TX_REQUEST | raw LoRa bytes | TX_DONE 0x02 (4 B airtime, microseconds LE) or TX_FAIL 0x03 |
| 0x04 | RX_PACKET | (never - modem to host only) | see below |
| 0x10 | SET_CONFIG | 14 B config | CONFIG_RESP 0x12 |
| 0x11 | GET_CONFIG | - | CONFIG_RESP 0x12 |
| 0x20 | STATUS_REQ | - | STATUS_RESP 0x21 |
| 0x22 | NOISE_REQ | - | NOISE_RESP 0x23 |
| 0x30 | CAD_REQUEST | - | CAD_RESP 0x32 (1 B: 0x00 clear, 0x01 busy) |
| 0x31 | RX_START | - | RX_STARTED 0x33 |
| 0x34 | SET_CAD_PARAMS | 4 B (symNum, detPeak, detMin, exitMode) | CAD_PARAMS_RESP 0x35 (echo) |
| 0x50 | AUTH | token bytes | AUTH_OK 0x51 |
| 0x70 | GET_VERSION | - | VERSION_RESP 0x71 (2 B: version, 0) |
| 0xFF | PING | - | PONG 0xFF |
| 0xFE | ERROR | (never - modem to host only) | - |

### STATUS_RESP (0x21) payload

24 bytes, little-endian: `<IIIIhhhbB>`

uptime (u32) | rx_count (u32) | tx_count (u32) | crc_errors (u32)
last_rssi (i16) | snr x10 (i16) | noise x10 (i16) | temp_c (i8) | radio_state (u8)

### ERROR (0xFE) codes

| Code | Meaning |
|---|---|
| 0x01 | CRC mismatch on received frame |
| 0x02 | Unknown command |
| 0x03 | Radio busy |
| 0x04 | TX timeout |
| 0x05 | Payload too big |
| 0x06 | Invalid config |
| 0x07 | CAD failed |
| 0x08 | Radio init failure |
| 0x09 | Unauthorized (bad token) |

## Unsolicited frames (modem to host)

### RX_PACKET (0x04) - the receive feed

Sent for every packet the radio hears. Payload:

```
RSSI i16 LE | SNR x10 i16 LE | signal-RSSI i16 LE | raw LoRa bytes
```

This is openHop's entire receive feed in `no_tx` mode.

### TX_DONE (0x02) / TX_FAIL (0x03)

Sent in response to TX_REQUEST (or spontaneously on failure).

## The TX loopback (why meshtech-modem exists)

A LoRa radio never hears its own transmissions. In the target setup
the MeshTech bot owns the radio, so packets **the bot sends** are
invisible to openHop unless they are fed back explicitly.

meshtech-modem therefore receives two streams from the bot's MCP
module and merges them into one RX broadcast feed:

1. everything the radio receives over the air
2. everything the bot transmits (looped back with synthetic metadata)

openHop's packet log and MQTT stream stay complete without the bot and
openHop fighting over the hardware.

## LBT / channel sensing

The host driver runs its own listen-before-talk loop: repeated
CAD_REQUEST probes with random backoff, transmitting anyway after its
max attempts. The modem answers each CAD probe honestly. In the
target setup the bot's MCP is the single LBT brain for real
transmissions; CAD answers to openHop are always "busy" while the MCP
holds the air or "honest" channel state otherwise.
