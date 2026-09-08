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

Running on the bench Linux box as a systemd service, verified
end-to-end with openHop Repeater (connect, handshake, packet parse).
The radio feed side is being built alongside the bot's MCP module -
until it exists, the `demo_feed` option injects synthetic packets
for testing.

## Install & run (Linux)

One-time, inside a clone of this repo:

```
./install.sh
```

That creates the virtualenv, installs dependencies, and installs a
systemd service (`meshtech-modem`) that starts on boot and restarts
if it crashes. You never touch the virtualenv.

Settings live in `modem.conf` in the repo folder (created from
`modem.conf.example` on first install): listen host and port, optional
auth token, and the demo feed switch. After editing it:

```
sudo systemctl restart meshtech-modem
```

Everyday commands:

- `systemctl status meshtech-modem` - is it running?
- `journalctl -u meshtech-modem -f` - live log (connections, config,
  demo packets)

Updating to a new version:

```
git pull && sudo systemctl restart meshtech-modem
```

## Testing without a radio (demo feed)

With `demo_feed = true` in `modem.conf`, the modem injects a signed
advert for a node called `DEMO` every `demo_interval` seconds (10 by
default). openHop parses it and shows the node with a live last-seen
time - proof the whole receive path works with no radio attached.

Leave it off in normal use: it broadcasts to the mesh every interval
for as long as it is on.

## Docs

- [PROTOCOL.md](PROTOCOL.md) - the wire protocol this program speaks
- [CHANGELOG.md](CHANGELOG.md) - what changed in each version

## License

MIT - see [LICENSE](LICENSE). Third-party attributions are in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
