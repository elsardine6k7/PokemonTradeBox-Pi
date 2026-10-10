# PokemonTradeBox-Pi

Touchscreen Raspberry Pi frontend for [pokeldn](https://github.com/Decryptu/pokeldn).

Portable 800×480 Raspberry Pi trade-box UI with touch-friendly Pokémon building, local wireless trades, Mystery Gifts, FireRed/LeafGreen tools, status checks, and optional Labwc autostart.

## Features

- Legends Z-A local trades
- Sword / Shield Link Trades and Mystery Gifts
- FireRed / LeafGreen Direct Corner trades, Wonder Cards, Wonder News, and read-only save/trainer info
- touch-first six-Pokémon team builder
- species / move / held-item / ball pickers
- large `- / +` controls for level, EVs, quantities, BP, money, and card IDs
- friendship / happiness selection
- compact GTK4 layout tuned for 800×480
- ESP32 reset/status handling
- pokeldn / PKHeX status page
- Labwc autostart helper

The original setup was tested on a Raspberry Pi 4, an 800×480 DSI touchscreen, and a CP2102 ESP32 radio.

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

See [docs/setup.md](docs/setup.md) and [docs/hardware.md](docs/hardware.md).

## Friendship / Happiness

pokeldn v0.20.0 did not yet forward Showdown Happiness/Friendship into the PKHeX builder. This repo includes `patches/pokeldn-friendship.patch`.

```bash
cd ~/pokeldn
git apply ~/PokemonTradeBox/patches/pokeldn-friendship.patch
dotnet build -c Release services/pkhex
```

The upstream proposal is [Decryptu/pokeldn#14](https://github.com/Decryptu/pokeldn/pull/14).

## Privacy

`config.json` is ignored by Git. Never commit `prod.keys`.

## License

AGPL-3.0, matching pokeldn.

Pokémon is a trademark of Nintendo / Creatures / GAME FREAK. This is an unofficial community project and is not affiliated with or endorsed by them.
