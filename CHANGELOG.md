# Changelog

## v0.4.2

- made STOP respond immediately while GTK timers monitor the exact launcher PID
- preserved SIGINT, the 15-second graceful-exit window, and SIGTERM followed by up to 5 seconds
- moved serial reset delays to a worker thread, after the launcher exits
- reserved the radio throughout shutdown, reset, and each firmware-helper operation
- blocked competing trades, gift writes, STOP/reset, and board actions while the radio is reserved
- cancelled pending actions after failed shutdowns; a late process exit releases the reservation without starting the cancelled action
- prevented stale process watchers from reporting against a replacement session
- handled reset-worker and launcher/helper startup failures without leaving the radio reserved
- blocked window closing during radio operations and gracefully stopped running sessions before closing
- added hardware-independent shutdown and callback regression tests and an Ubuntu CI workflow
- updated install syntax checks for the new session controller
- Pi touchscreen and ESP32 hardware validation is pending

## v0.4.1

- aligned TradeBox with pokeldn v0.23.0+ and its documented Program Surface 1.3 stable API
- simplified Sword/Shield custom Nature handling to use the supported gift-builder state and `swgift.compile()`
- removed TradeBox's manual WC8 Nature byte patching and resealing path
- changed session shutdown to signal only the exact pokeldn PID TradeBox launched
- session shutdown now sends SIGINT first, waits up to 15 seconds, then sends SIGTERM if needed
- removed launcher-name `pkill -f` cleanup so TradeBox cannot stop a pokeldn run started by another program
- removed the unnecessary separate process group created for launchers
- verified explicit Sword/Shield gift Nature delivery end-to-end on pokeldn v0.23.0
- verified STOP follows the new PID-only shutdown path


## v0.4.0

- added a touchscreen ESP32 / Firmware manager to the home screen
- added Check Board for connected port, chip, installed firmware, protocol compatibility, and downloaded firmware
- added Check / Download Latest using pokeldn's official release downloader and SHA256 verification
- added guarded ESP32 flashing through pokeldn's own chip detection, image validation, checksum verification, and esptool path
- added a confirmation screen and blocked TradeBox STOP/reset while a firmware operation is active
- added per-operation ESP32 logs under `logs/`
- tested the full check → download/verify → flash → re-check flow on a classic ESP32 with a CP2102 USB bridge and pokeldn radio firmware 1.6.1
- documented the `esptool==5.4.0` requirement for source-checkout installations of pokeldn
- install checks now syntax-check the ESP32 helper and warn when esptool is missing


## v0.3.0

- added a FireRed / LeafGreen chooser before entering FR/LG tools
- selected FR/LG version now controls Direct Corner, Mystery Gift, Wonder News, and save-reading hosts
- resized and wrapped the FR/LG Mystery Gift list for the 800×480 touchscreen
- made Wonder News use the persistent touch scrollbar
- added Build Your Own for FR/LG: Wonder Card, Wonder News, and Console Code
- custom FR/LG Wonder Cards compile through pokeldn, save as .pokegift, and are then hosted through frlg_mg_host.py
- custom Wonder Card delivery was tested successfully in-game
- kept BDSP limited to Link Trade and Received Pokémon; BCAT is not exposed in the Pi UI

## v0.2.0

- added Brilliant Diamond / Shining Pearl local Union Room trading
- added BDSP received-Pokémon history
- added BDSP trainer configuration
- added permanent, larger touch-friendly vertical scrollbars
- settings now show the PokemonTradeBox-Pi version
- friendship status recognizes both the current upstream implementation and the older v0.20.0 compatibility patch
- documentation updated after the friendship contribution was merged into pokeldn
- BCAT / Wonder Card injection is intentionally not exposed in the Pi UI

## v0.1.0

- initial public Raspberry Pi touchscreen release
