# PokemonTradeBox-Pi

**Current version: v0.3.0**

Touchscreen Raspberry Pi frontend for [pokeldn](https://github.com/Decryptu/pokeldn).

Portable 800×480 Raspberry Pi trade-box UI with touch-friendly Pokémon building, local wireless trades, Mystery Gifts, FireRed/LeafGreen tools, status checks, and optional Labwc autostart.

## Features

- Legends Z-A local trades
- Sword / Shield Link Trades and Mystery Gifts
- Brilliant Diamond / Shining Pearl local Union Room trades and received-Pokémon history
- FireRed / LeafGreen game selector, Direct Corner trades, Mystery Gift presets, Wonder News, read-only save/trainer info, and Build Your Own Wonder Card / Wonder News / Console Code tools
- touch-first six-Pokémon team builder
- species / move / held-item / ball pickers
- large `- / +` controls for level, EVs, quantities, BP, money, and card IDs
- friendship / happiness selection
- compact GTK4 layout tuned for 800×480
- permanent touch-sized vertical scrollbars that do not fade away
- ESP32 reset/status handling
- pokeldn / PKHeX status page
- Labwc autostart helper

The original setup was tested on a Raspberry Pi 4, an 800×480 DSI touchscreen, and a CP2102 ESP32 radio. The custom FR/LG Wonder Card builder has also been tested end-to-end in-game.

## Requirements

Install and verify [pokeldn](https://github.com/Decryptu/pokeldn) first. The default config expects it at `~/pokeldn`.

You must provide your own compatible hardware, `prod.keys`, and trainer metadata. This repository does not contain console keys, ROMs, saves, or Nintendo game data.

On Raspberry Pi OS:

```bash
sudo apt update
sudo apt install python3-gi gir1.2-gtk-4.0 python3-serial squeekboard wfplug-squeek
```

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
