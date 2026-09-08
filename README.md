# meshtech-modem

A small program that lets [openHop Repeater](https://github.com/openhop-dev/openhop_repeater)
share a LoRa radio it doesn't own.

## The problem it solves

A LoRa radio (like the Waveshare SX1262 Pi HAT) can only be driven by
one program at a time. If the MeshTech bot owns the radio, openHop
has nothing to listen with.

meshtech-modem fixes that. It pretends to be an openHop modem: openHop
connects to it over TCP, believes it is talking to real modem hardware,
and receives every packet the radio hears.

## How it fits together

```
+---------------------+        +---------------------+
|     MeshTech bot    |        |   meshtech-modem    |
|  (owns the radio)   |  RX    |  (this program)     |
|                     |--feed->|                     |
|  sends every packet |        |  serves openHop     |
|  it hears or sends  |        |  over TCP :5055     |
+---------------------+        +----------+----------+
                                          |
                                          v
                            openHop Repeater (no_tx mode)
                            web console, packet log, MQTT
```

- The bot's MCP module owns the radio hardware.
- meshtech-modem connects to the bot and receives a copy of every
  packet the radio hears **and every packet the bot transmits** (a
  radio never hears its own transmissions, so the bot feeds those back
  explicitly).
- openHop connects to meshtech-modem as if it were a `pymc_tcp` modem,
  set to `no_tx` mode. It never transmits; it just listens and does
  its observation job.

## Status

Early development. The protocol implementation is complete (decoded
from openhop-core's driver and the openhop_modem firmware source);
the radio feed side is being built alongside the bot's MCP module.

## Docs

- [PROTOCOL.md](PROTOCOL.md) - the wire protocol this program speaks
- [CHANGELOG.md](CHANGELOG.md) - what changed in each version

## License

MIT - see [LICENSE](LICENSE). Third-party attributions are in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
