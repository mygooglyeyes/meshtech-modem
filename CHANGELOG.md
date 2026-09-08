# Changelog

Every change gets its own version number - the version doubles as a
commit counter. This file records what each change does, in plain
language, newest first.

Going forward: every commit that bumps the version adds its line here.

## 0.0.003 - 2026-09-08

CI: GitHub Actions workflow runs the protocol test suite on every
push to DEV and every pull request to main
(.github/workflows/tests.yml).

## 0.0.002 - 2026-09-08

Add requirements-dev.txt pinning the test dependencies (pytest,
pytest-asyncio, pytest-timeout), so the test environment is one
command: python -m pip install -r requirements-dev.txt

## 0.0.001 - 2026-09-08

Project start. Protocol implementation decoded from openhop-core's
TCPLoRaRadio driver and the openhop_modem firmware source:

- Frame format (SYNC | CMD | LEN | PAYLOAD | CRC-16/CCITT-FALSE)
- Full command table: AUTH, PING, SET_CONFIG, CAD, TX, RX_START,
  STATUS, NOISE, SET_CAD_PARAMS, GET_VERSION
- RX broadcast to the connected host (RSSI/SNR/signal-RSSI metadata)
- TX loopback feed: packets the bot transmits are re-broadcast so
  openHop sees the bot's own traffic
- Protocol tests (framing, CRC vectors, command round-trips)
