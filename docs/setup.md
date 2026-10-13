# Setup

Copy `config.example.json` to `config.json` and enter your own trainer metadata.

For Sword / Shield, Brilliant Diamond / Shining Pearl, and Legends Z-A, pokeldn's builder/host uses raw trainer ID values. These may differ from the formatted IDs displayed in-game.

Set `frlg_version` to `firered` or `leafgreen`.

The recommended radio setting is `"auto"`, which TradeBox passes to pokeldn as `esp32:auto`.

The default key path is `~/.switch/prod.keys`. Supply your own keys from hardware you are authorized to use.

Manual Wayland launch:

```bash
XDG_RUNTIME_DIR=/run/user/$(id -u) \
WAYLAND_DISPLAY=wayland-0 \
DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$(id -u)/bus \
GDK_BACKEND=wayland \
python3 ~/PokemonTradeBox/tradebox.py
```


## Brilliant Diamond / Shining Pearl

Add a `bdsp` trainer entry to `config.json` using the original trainer name plus raw TID/SID values. TradeBox v0.2.0 hosts a local Union Room with `bin/bdsp_host.py`, completes the trade, and saves the partner's received records as `received-bdsp_*.pb8`.

BCAT / Wonder Card injection is intentionally not part of the Pi UI.


## FireRed / LeafGreen

TradeBox v0.3.0 asks you to choose FireRed or LeafGreen when entering the FR/LG section. That selection controls the Direct Corner trade host, Mystery Gift host, Wonder News host, and read-only save tools for the current session.

The **Build Your Own** menu uses pokeldn's FR/LG gift builder. It can create a Wonder Card, Wonder News, or advanced Console Code payload, saves the result as a local `.pokegift`, then starts `bin/frlg_mg_host.py` with that file. The custom Wonder Card path has been tested successfully in-game.

Console Code is an advanced feature that runs ARM code during the Mystery Gift session. Use code you understand; assembly source requires the GNU Arm toolchain, while pokeldn can also use a compatible prebuilt `.bin`.


## ESP32 firmware manager

TradeBox v0.4.0 adds **ESP32 / FIRMWARE** to the home screen. It reuses pokeldn's board-management code instead of maintaining a separate flasher.

For a pokeldn source checkout, make sure esptool is installed in pokeldn's virtual environment:

```bash
~/pokeldn/.venv/bin/python -m pip install esptool==5.4.0
```

The three actions are:

- **CHECK BOARD** — opens the configured serial port, reads pokeldn firmware identity, chip type, installed firmware version and protocol compatibility, and reports the locally downloaded radio image version when available.
- **CHECK / DOWNLOAD LATEST** — asks pokeldn for the newest published official release that carries firmware images, verifies the release asset source and SHA256SUMS, then writes the official radio/controller images into `~/pokeldn/gui/firmware/`.
- **FLASH ESP32** — after an explicit confirmation screen, uses pokeldn's chip detection and validation before writing. The helper refuses unsupported chips, missing images, chip/image mismatches, invalid merged images and checksum failures before flashing.

TradeBox disables its normal STOP/reset path while a firmware operation is active. Do not disconnect USB or power during a flash.

The v0.4.0 flow was tested end-to-end on a classic ESP32 with a CP2102 USB bridge: board check, official v0.22.2 firmware download/verification, flashing radio firmware 1.6.1, and a successful post-flash board check.


## Updating PokemonTradeBox-Pi on the Pi

For an install created with `git clone`, SSH into the Pi and run:

```bash
cd ~/PokemonTradeBox
git status --short
git pull --ff-only
./install.sh
cat VERSION
sudo reboot
```

What those commands do:

- `git status --short` checks for local edits before updating.
- `git pull --ff-only` downloads the newest GitHub version without creating an accidental merge commit.
- `./install.sh` rechecks executable permissions, creates any missing local folders/config, and runs a Python syntax check.
- `cat VERSION` shows the installed PokemonTradeBox-Pi version.
- `sudo reboot` is the simplest way to restart a Labwc-autostart installation on the updated code.

A normal Git update preserves `config.json`, `logs/`, `gifts/`, received Pokémon files, and the FR/LG dump files because they are excluded by `.gitignore`.

If `git status --short` shows local changes to tracked files, make a full backup first:

```bash
cp -a ~/PokemonTradeBox ~/PokemonTradeBox.backup-$(date +%Y%m%d-%H%M%S)
```

Do not blindly run `git reset --hard` on a customized installation. Either copy the local changes somewhere safe, stash them, or manually reconcile them with the updated GitHub version.

If the original installation was copied onto the Pi instead of cloned with Git, clone a fresh copy of the repository and move the old `config.json` into the new folder before starting TradeBox.
