# Changelog

## v0.6.1

- added the missing Scarlet/Violet Link Trade menu and connected the existing touch team/Showdown builder to PokeLDN's native host settings
- retained local trading without a code, legal-offer checks, automatic received-Pokemon banking, and native save/exit handling
- Rick confirmed BDSP simulated Mystery Gift delivery works on the Switch

## v0.6.0

- added Mystery Gift - Simulated for Legends Z-A, Scarlet/Violet, and BDSP using PokeLDN's event service and native catalog hosts
- added searchable event lists, gift details and HOME warnings, separate six-gift queues, and prepared-offer review before hosting
- enabled receiving-player trainer handling where supported; retained fixed event trainers and surfaced host fallback notices in the gift queue
- added Scarlet/Violet trainer configuration, Bank destinations, and confirmed received-Pokemon banking
- kept the host connected through saving and exit; gift trades never remove existing outgoing Bank records
- detected simulated gift support separately at startup so existing tools remain usable with older backends
- arranged the eight home actions in a touchscreen grid

## v0.5.0

- automatically banked confirmed received Pokemon from regular and Bank trades, preserving received bytes and legality warnings
- tracked received files by unique run and trade number, with retry/recovery journaling and duplicate handling
- added a touchscreen Bank using PokeLDN's documented API 1.4
- imported Pokemon files and saves without changing their sources, with duplicate/refusal counts and conversion notes
- added paginated browsing/search, destination checks, and explicit Bank-copy deletion
- moved browsing onto its own touchscreen page, with compact touch rows and preserved search, page, and scroll position
- added a six-slot ordered Bank queue for Z-A, Sword/Shield, BDSP, and FR/LG, with converted-offer confirmation before hosting
- preserved banked Pokemon identities by omitting --fresh-pid and using the native launcher flags
- removed Bank records only through TradeSession.advance() from confirmed launcher completion lines; kept the host connected through the Switch's save and room-exit handshakes
- prevented Bank progress/inspection errors from interrupting a running host while the Switch saves
- drained final confirmations before resetting or replacing a Bank host, preserving uncompleted records on STOP
- isolated Bank work in the backend venv and a separate Bank folder, with a single-writer lock
- saved run receipts and logs for explicit reconciliation after interrupted workers or app restarts
- ignored stale callbacks and refused reconciliation while the recorded host is still alive
- kept the other TradeBox tools available on API 1.3; Bank requires API 1.4
- verified compatibility with PokeLDN v0.25.0 and Program API 1.4 on the Pi
- added Bank, callback, worker, and 800x480 GTK layout checks
- Rick confirmed a Bank Metapod trade completes saving, returns to trade selection, exits through CANCEL/YES, and leaves the Pokemon on the Switch; received duplicate handling and clean host shutdown also passed

## v0.4.3

- opened the touchscreen before loading configuration or PokeLDN dependencies
- added startup diagnostics and Retry for invalid JSON, trainer values, missing checkout/venv, incompatible PokeLDN/API versions, and failed PKHeX health checks
- checked API compatibility in the configured PokeLDN venv and required builder imports in the touchscreen's Python, without loading user plugins
- avoided importing the full tool catalog into touchscreen diagnostics, which incorrectly required unrelated dependencies such as Crypto
- bounded PKHeX diagnostics in a separate process; timeout cleanup targets only that diagnostic and its own helper
- kept builders available with warnings when keys, serial tools, firmware tools, or the ESP32 are missing
- checked keys only for hosts that need them, and rechecked radio/key availability before stopping and before starting a replacement host
- added startup-check results and a rerun button to Settings; cached species counts keep this page from making blocking health requests
- made the installer respect pokeldn_repo and POKEMON_TRADEBOX_CONFIG, preserving existing configuration
- added configuration, backend, Retry, disconnect, timeout-cleanup, and configured-path installer regression tests
- Rick confirmed the Pi's Settings/startup status, offline team editing with the ESP32 disconnected, and reconnecting to trade, STOP, and start another trade

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
- Rick confirmed STOP works and the ESP32 resets quickly on the Pi

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
