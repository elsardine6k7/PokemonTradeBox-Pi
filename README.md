# PokemonTradeBox-Pi

**Current version: v0.6.1**

Touchscreen Raspberry Pi frontend for [pokeldn](https://github.com/Decryptu/pokeldn).

Portable 800×480 Raspberry Pi trade-box UI with touch-friendly Pokémon building, local wireless trades, Mystery Gifts, FireRed/LeafGreen tools, status checks, and optional Labwc autostart.

## Features

- Legends Z-A local trades
- Scarlet / Violet local Link Trades with the touch team builder and Showdown input
- Mystery Gift - Simulated for Legends Z-A, Scarlet / Violet, and BDSP, with event search and a six-gift queue
- Sword / Shield Link Trades and Mystery Gifts
- Brilliant Diamond / Shining Pearl local Union Room trades and received-Pokémon history
- FireRed / LeafGreen game selector, Direct Corner trades, Mystery Gift presets, Wonder News, read-only save/trainer info, and Build Your Own Wonder Card / Wonder News / Console Code tools
- touch-first six-Pokémon team builder
- species / move / held-item / ball pickers
- large `- / +` controls for level, EVs, quantities, BP, money, and card IDs
- friendship / happiness selection
- compact GTK4 layout tuned for 800×480
- permanent touch-sized vertical scrollbars that do not fade away
- ESP32 board check, official firmware download/verification, and guarded firmware flashing
- ESP32 reset/status handling
- responsive STOP and exclusive radio operations during shutdown, reset, and firmware work
- pokeldn / PKHeX status page
- startup diagnostics with Retry, offline editing when the ESP32 is disconnected, and configured-path install checks
- Bank imports, automatic banking of confirmed received Pokemon, browsing, conversion previews, and a six-slot trade queue through stable API 1.4
- Labwc autostart helper

The original setup was tested on a Raspberry Pi 4, an 800×480 DSI touchscreen, and a CP2102 ESP32 radio. The custom FR/LG Wonder Card builder has been tested end-to-end in-game, and the v0.4.0 ESP32 firmware manager was tested end-to-end on a classic ESP32/CP2102, including downloading, verifying, flashing, and re-checking official pokeldn radio firmware.

## Requirements

Install and verify [pokeldn](https://github.com/Decryptu/pokeldn) **v0.23.0 or newer** first. The Bank feature needs **v0.24.0+ / Program API 1.4**. Other TradeBox tools use Program Surface 1.3, including native Sword/Shield gift Nature support. The default config expects pokeldn at `~/pokeldn`.

You must provide your own compatible hardware, `prod.keys`, and trainer metadata. This repository does not contain console keys, ROMs, saves, or Nintendo game data.

On Raspberry Pi OS:

```bash
sudo apt update
sudo apt install python3-gi gir1.2-gtk-4.0 python3-serial squeekboard wfplug-squeek
```

The ESP32 firmware manager uses pokeldn's stable `gui.board` API and `esptool`. For a source checkout of pokeldn, install the esptool version required by that pokeldn release (v0.22.2 uses 5.4.0):

```bash
~/pokeldn/.venv/bin/python -m pip install esptool==5.4.0
```

## pokeldn compatibility

TradeBox uses pokeldn's documented **Program Surface 1.3** (API major 1) for the Pokémon builder, gift builders, gift-file helpers, and `gui.board`, plus **API 1.4** for Bank operations and confirmed trade completion. Simulated gifts use the documented event service and built-in catalog host tools; startup detects these separately so older backends can still use the other tools.

The Pi installation is validated with **PokeLDN v0.29.1 / API 1.8**.

## Mystery Gift - Simulated (v0.6.0)

Open **LEGENDS Z-A**, **SCARLET / VIOLET**, or **BRILLIANT DIAMOND / SHINING PEARL**, then **MYSTERY GIFT - SIMULATED**. Search official event Pokemon, inspect a gift, add up to six to the gift queue, and prepare them for review before starting. The console trades one Pokemon for each gift; confirmed received Pokemon are automatically banked.

**Made for the receiving player** is on by default for gifts that support it. Gifts with a fixed event trainer retain that trainer. Keep the host running until the Switch finishes saving and leaves trading after the last gift. See the [gift guide](docs/simulated-gifts.md) for console steps, trainer settings, and HOME warnings.

For ordinary Scarlet/Violet trades, open **SCARLET / VIOLET → LINK TRADE**, build up to six Pokemon, then start hosting. On the Switch, use **Poke Portal → Link Trade**, offline, with no Link Code. Received Pokemon are automatically banked after confirmed completion.

## Pokemon Bank (v0.5.0)

Open **POKEMON BANK** on Home to import a Pokémon file or save, browse stored records, choose a trade destination, and queue up to six different Pokémon. Converted offers are shown before starting the host. Only confirmed completed trades remove Bank records; cancelling or stopping preserves the uncompleted records. Keep the host running while the Switch finishes saving, then exit trading on the Switch so PokeLDN can close the connection normally.

Pokemon received from the retail game in regular link trades and Bank trades are automatically added after confirmed completion, as PokeLDN writes the received files. Final host shutdown also collects any late files. **IMPORT FILE / SAVE** remains available.

TradeBox keeps its Bank separately from the desktop app and performs Bank work in PokeLDN's venv. Current trade destinations are Z-A, Scarlet/Violet, Sword/Shield, BDSP, FireRed, and LeafGreen. See [Bank usage and Pi test checklist](docs/bank.md) for imports, trainer selection, recovery, and saved received files.

TradeBox also follows pokeldn's launcher shutdown contract: it sends **SIGINT only to the PID it started**, waits up to 15 seconds for a clean exit, then sends **SIGTERM** if needed. It does not use `pkill -f` or match launcher names, so it will not stop a pokeldn run started by another program.

In v0.4.2, STOP shows **Stopping...** immediately and monitors the process with GTK timers. The ESP32 reset runs in a worker thread after the process exits, so the touchscreen stays responsive throughout shutdown. The graceful-exit timing remains 15 seconds, followed by up to 5 seconds after SIGTERM. A process that remains running blocks new sessions and board operations; its pending replacement is cancelled even if it exits later.

Trade starts, board checks/downloads/flashes, and STOP share one radio reservation. A new trade cannot reset the ESP32 during firmware work. Closing the window during a board operation is blocked; closing it during a running trade first requests the same graceful shutdown.

Sword/Shield custom gifts now pass Nature directly through pokeldn's gift-builder state and `swgift.compile()`; TradeBox no longer patches or reseals WC8 bytes itself. This path was tested end-to-end against pokeldn v0.23.0 with an explicitly selected Nature.

Upstream API reference: [pokeldn Program Surface 1.3](https://github.com/Decryptu/pokeldn/blob/main/docs/plugins.md#the-program-surface-13).

## Install

```bash
git clone https://github.com/elsardine6k7/PokemonTradeBox-Pi.git ~/PokemonTradeBox
cd ~/PokemonTradeBox
chmod +x install.sh start-tradebox.sh
./install.sh
nano config.json
./start-tradebox.sh
```

Optional Labwc autostart:

```bash
./install.sh --autostart
```

### ESP32 firmware manager

From the TradeBox home screen, open **ESP32 / FIRMWARE**.

- **CHECK BOARD** reads the connected board, chip type, installed radio-firmware version, protocol compatibility, and the version of any firmware already downloaded on the Pi.
- **CHECK / DOWNLOAD LATEST** uses pokeldn's official release downloader, validates the release source and SHA256 checksums, and stores the official firmware images in the pokeldn checkout.
- **FLASH ESP32** shows a confirmation screen, then calls pokeldn's own chip-detection, image-validation, checksum-verification, and esptool flashing path. TradeBox blocks its normal STOP/reset action while a firmware operation is in progress.

Do not disconnect USB or power while flashing.

## Update an existing Pi install

If PokemonTradeBox-Pi was installed with `git clone`, update it directly on the Pi:

```bash
cd ~/PokemonTradeBox
git status --short
git pull --ff-only
./install.sh
cat VERSION
sudo reboot
```

`config.json`, logs, generated gifts, and received Pokémon files are ignored by Git, so a normal update does not replace them.

If `git status --short` shows changes to tracked project files such as `tradebox.py`, make a backup before updating:

```bash
cp -a ~/PokemonTradeBox ~/PokemonTradeBox.backup-$(date +%Y%m%d-%H%M%S)
```

Then either keep/reapply those local changes manually or return the tracked files to the GitHub version before pulling. Avoid using a forced reset unless you are sure you do not need the local edits.

If the existing TradeBox folder was copied manually instead of cloned from GitHub, the easiest upgrade is to clone a fresh copy and move your existing `config.json` into it.

See [docs/setup.md](docs/setup.md) and [docs/hardware.md](docs/hardware.md).

## Regression checks

The shutdown controller and actual TradeBox process callbacks have hardware-independent regression tests. They use fake processes, a controlled clock, and a simulated GTK scheduler, so they need neither GTK nor a pokeldn checkout:

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile tradebox.py esp32_manager.py session_control.py
bash -n install.sh start-tradebox.sh
```

GitHub Actions runs these checks on Ubuntu with Python 3.12. They cover PID-only signalling, grace-period timing, competing radio operations, reset and startup failures, and cancelled requests after failed shutdowns. Rick confirmed v0.4.2 STOP and ESP32 reset working on the Pi. Additional device checks are documented in [the test checklist](docs/setup.md#v042-hardware-check).

## Friendship / Happiness

Friendship support was merged upstream in [Decryptu/pokeldn#14](https://github.com/Decryptu/pokeldn/pull/14).

Use a current pokeldn build when possible. If you intentionally stay on pokeldn v0.20.0, this repo keeps the older compatibility patch at `patches/pokeldn-friendship.patch`:

```bash
cd ~/pokeldn
git apply ~/PokemonTradeBox/patches/pokeldn-friendship.patch
dotnet build -c Release services/pkhex
```

The v0.20.0 compatibility patch was originally validated with Sword / Shield. Current upstream pokeldn contains the maintained cross-game implementation.

## Privacy

`config.json` is ignored by Git. Never commit `prod.keys`.

## Credits & acknowledgements

PokemonTradeBox-Pi is a touchscreen frontend built around the work of the wider **pokeldn** community. Credit for the local-wireless protocols, ESP32 radio stack, game hosts, event data support, and related reverse-engineering belongs to those upstream projects and contributors.

Special thanks to:

- [Decryptu](https://github.com/Decryptu) for maintaining and developing [pokeldn](https://github.com/Decryptu/pokeldn), which PokemonTradeBox-Pi uses as its backend.
- [MercuryEnigma](https://github.com/MercuryEnigma) and [tornadus](https://github.com/tornadus) for the original frlg-ldn-trade project lineage, with contributions from [trowgundam](https://github.com/trowgundam).
- [kinnay](https://github.com/kinnay) for the [LDN library](https://github.com/kinnay/LDN) and NintendoClients research used by pokeldn.
- [Gr3nSkyDragon](https://github.com/Gr3nSkyDragon) for ESP32-S3 firmware work in pokeldn.
- [ismailhasannnnnn](https://github.com/ismailhasannnnnn) for Scarlet/Violet Tera Raid hosting and joining work.
- [easyworld](https://github.com/easyworld) for ESP32 serial reconnect improvements.
- [capito27](https://github.com/capito27) for Scarlet/Violet event Tera Raid, reward-search, seed-search, size-mark, and NPC partner work in pokeldn.
- [xCyrusBR](https://github.com/xCyrusBR) for TeraLoop-related Scarlet/Violet raid work.
- [Matcore962](https://github.com/Matcore962) for Pokémon file and save importing work used by pokeldn's Bank.
- [GB-Link Team](https://github.com/GB-Link/GB-Link-Switch-LDN) for the custom FireRed/LeafGreen Wonder Cards used by pokeldn.
- [pret/pokefirered](https://github.com/pret/pokefirered) for the FireRed/LeafGreen decompilation work, including the Switch port.
- [Project Pokémon](https://github.com/projectpokemon) for the [EventsGallery](https://github.com/projectpokemon/EventsGallery) event data used by pokeldn.
- [PKHeX](https://github.com/kwsch/PKHeX) and its contributors for the legality and Pokémon data tooling used by pokeldn.

The upstream pokeldn project maintains its own detailed credits list; see its [README](https://github.com/Decryptu/pokeldn#credits) for the authoritative upstream attribution.
## License

AGPL-3.0, matching pokeldn.

Pokémon is a trademark of Nintendo / Creatures / GAME FREAK. This is an unofficial community project and is not affiliated with or endorsed by them.
