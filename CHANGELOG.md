# Changelog

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
