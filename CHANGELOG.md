# Changelog

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
