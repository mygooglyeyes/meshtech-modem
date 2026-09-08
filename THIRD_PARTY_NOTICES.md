# Third-Party Notices

Software and documentation this project is built on, and what each
contributed.

## openhop_core

- **What:** Python implementation of the MeshCore protocol, including
  the `TCPLoRaRadio` driver (`hardware/tcp_radio.py`) and
  `protocol_constants.py` that define the pymc_tcp modem wire protocol
  this project implements.
- **Where:** https://github.com/openhop-dev/openhop_core
- **License:** MIT
- **How used:** The wire protocol (frame format, command codes, CRC,
  struct layouts) was decoded from this driver's source so
  meshtech-modem can emulate the modem it expects. No code is copied;
  the protocol constants were transcribed and verified.

## openhop_modem

- **What:** Firmware for openHop's dedicated LoRa modem boards. Its
  `main.cpp`, `tcp_server.cpp`, and `frame_parser.cpp` define the
  modem-side behaviour (auth, CAD answers, TX_DONE payload, RX
  broadcast format) that this project reproduces.
- **Where:** https://github.com/openhop-dev/openhop_modem
- **License:** MIT (implied by repository)
- **How used:** Behavioural reference for the emulation; no code copied.

## openHop Repeater

- **What:** The repeater daemon this project serves. Its
  `radio_type: pymc_tcp` + `mode: no_tx` configuration is the
  integration target.
- **Where:** https://github.com/openhop-dev/openhop_repeater
- **License:** MIT
- **How used:** Integration target only; not included or modified.

## MeshCore

- **What:** The underlying mesh protocol all of these implement.
- **Where:** https://github.com/meshcore-dev/meshcore
- **License:** See upstream repository
- **How used:** Packet formats and the KISS modem protocol spec
  (docs.meshcore.io) informed the design. No code copied.
