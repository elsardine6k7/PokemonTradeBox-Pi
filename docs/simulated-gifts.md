# Mystery Gift - Simulated

TradeBox v0.6.0 adds this feature to **Legends Z-A**, **Scarlet / Violet**, and **BDSP**. It uses PokeLDN's official event database and local trade host: the Switch receives a fresh legal event Pokemon and offers a Pokemon in return. No card download or Bank import is required.

## Choose and send gifts

1. Open the game on Home, then **MYSTERY GIFT - SIMULATED**.
2. Search by Pokemon, event title, moves, item, or card number. Tap a gift to inspect its trainer, moves, legality, and HOME warning.
3. Tap **ADD TO GIFT QUEUE**. Queue up to six, in trade order; the same event may be selected more than once. Each prepared copy is made fresh.
4. Open **QUEUE**, choose a code if needed, and leave **Made for the receiving player** enabled to use the Switch's trainer where the gift supports it.
5. Tap **PREPARE GIFTS**, review the gifts and console steps, then **START GIFT TRADES**.
6. Offer and trade one Pokemon from the Switch for each queued gift. After the last gift, let the Switch finish saving, then back out of trading. Keep TradeBox and the host running until you have left. Further trades repeat the final gift.

Preparing gifts runs outside the touchscreen thread and never starts a host. Received Pokemon are banked only after PokeLDN confirms their completed trade. Existing Bank copies are not offered or removed by gift trades. Interrupted receiving uses the Bank's normal retry/reconciliation flow.

## On the Switch

- **Z-A:** X → Link Play → Link Trade → Nearby Players. Enter the same eight-digit code as TradeBox (default `00000000`) and search. Offer a Pokemon, confirm, and back out with B after the last gift.
- **Scarlet / Violet:** X → Poke Portal → Link Trade, offline. The default is no code; optionally enter the same eight-digit Link Code on both sides. Search, offer, and confirm.
- **BDSP:** Start the host before entering the local Union Room. Pokemon Center 2F → left attendant → plain Yes, without a group or password by default. Use Y → Communicate → Trade Pokemon and accept the greeting. An optional eight-digit room password must match on both sides.

The prepared review also shows the instructions from the installed PokeLDN catalog.

## Trainers and gift restrictions

Gifts that originally named their receiver are made for the Switch's save when PokeLDN can identify it from the offered Pokemon or session. A Pokemon caught in that save is the clearest offer. Gifts with a fixed event trainer retain it. Some HOME starters require a handler and therefore use the configured trainer instead. Turning the receiving-player option off uses the configured trainer where the card permits.

Each game uses its own `trainers` entry in `config.json`. `trainers.sv` accepts the same raw 16-bit TID/SID, name, language, and gender as the other Switch games. An older config without `sv` uses a copy of the Z-A trainer in memory, preserving the existing trainer mapping; the file is not rewritten. Settings shows the trainer being used. Add an explicit `sv` entry to use different Scarlet/Violet details.

Illegal or refused gifts cannot be queued or hosted. A HOME warning remains visible even when the copy is legal: TradeBox follows PokeLDN's tracker setting and cannot issue a HOME tracker. If the host falls back to the configured trainer, the status directs you to the game's gift queue to read the reason.

## Compatibility and checks

Validated against **PokeLDN v0.29.1 / API 1.8**. Startup checks the event service, game tools, and PKHeX catalogs. Older backends keep their existing tools, with simulated gifts unavailable and an update message.

Automated checks cover catalog/command compatibility, legal preparation, queue ordering, refusal handling, receiving, and touchscreen pages. Rick confirmed BDSP simulated gift delivery works on the Switch. Z-A and Scarlet/Violet delivery and further queue/save/exit scenarios remain available for hardware testing.

Upstream references: [Simulated Mystery Gifts](https://github.com/Decryptu/pokeldn/blob/v0.29.1/docs/gift_simulated.md) and [program surface](https://github.com/Decryptu/pokeldn/blob/v0.29.1/docs/plugins.md#the-program-surface-13-bank-added-in-14-language-packs-in-15).
