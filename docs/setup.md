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


## pokeldn stable program surface

TradeBox v0.4.2 requires **pokeldn v0.23.0 or newer** and is written against pokeldn's documented **Program Surface 1.3** (API major 1). The supported surface includes the Pokémon builder, both Mystery Gift builders, gift-file helpers, and `gui.board`. pokeldn has an upstream test that resolves these supported names so external frontends do not need to depend on private internals.

TradeBox's Sword/Shield gift builder passes the selected Nature in the normal builder state and calls `pokeldn.swsh.gift_builder.compile(state)`. It does not directly edit or reseal WC8 bytes. Native Nature handling was added in pokeldn v0.23.0 and was verified end-to-end with TradeBox.

For launcher shutdown, TradeBox follows pokeldn's documented contract: SIGINT is sent to the exact process TradeBox launched, TradeBox waits up to 15 seconds, and SIGTERM is used only if the launcher is still running. TradeBox never searches for launcher names with `pkill -f`, so unrelated pokeldn sessions are left alone.

TradeBox v0.4.2 performs that wait through GTK timers and resets the radio in a worker thread. STOP changes the status immediately; it does not promise that the launcher will exit immediately. New sessions and board operations wait until shutdown and reset complete. If the launcher remains running after the additional 5-second SIGTERM window, the requested next action is cancelled and the radio stays reserved until that PID exits. Then retry the action explicitly.

See [pokeldn Program Surface 1.3](https://github.com/Decryptu/pokeldn/blob/main/docs/plugins.md#the-program-surface-13).


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

## v0.4.2 hardware check

Run these checks on the Pi before treating v0.4.2 as hardware-validated:

1. Start a normal trade host, tap STOP, and confirm **Stopping...** appears immediately. Navigate between pages while it stops; the touchscreen should continue responding.
2. Wait for **Stopped. ESP32 ready.**, then start another trade. The new session should connect normally.
3. With a host running, start **CHECK BOARD**. It should stop the old host and reset the radio before opening the firmware helper.
4. During **CHECK BOARD** or **CHECK / DOWNLOAD LATEST**, return to a game page and attempt to start a trade or gift. TradeBox should report that the ESP32 operation is in progress and leave the operation running. STOP and board-action buttons should stay disabled during the operation.
5. After the board operation completes, confirm STOP and board-action buttons work again and a normal trade can start.

These first checks do not require reflashing the ESP32. Flashing uses the same reservation and retains its existing explicit confirmation screen. The automated tests exercise failed-stop, reset, and process-start paths without using a real device.
