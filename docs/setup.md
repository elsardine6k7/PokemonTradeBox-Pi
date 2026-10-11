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
