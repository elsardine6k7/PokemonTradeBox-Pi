# Pokemon Bank

TradeBox v0.5.0 uses PokeLDN **v0.24.0+ / Program API 1.4** for Bank imports, records, conversions, and confirmed completion. The Bank runs in the configured PokeLDN venv; the touchscreen's system Python does not need the full desktop app's dependencies. The other TradeBox tools remain usable with API 1.3.

The Pi installation is validated with **PokeLDN v0.25.0 / API 1.4**. Its classic ESP32 can keep its working radio firmware; the v0.25.0 firmware change targets ESP32-S3 boards.

## Import and browse

1. Stop any host and wait for shutdown/reset to finish.
2. Open **POKEMON BANK** on Home. Records refresh automatically. Choose **BROWSE POKEMON** to open the dedicated list page.
3. Choose **TRADE INTO** to select Z-A, Sword/Shield, BDSP, FireRed, or LeafGreen. Clear the queue before changing its destination.
4. Choose **IMPORT FILE / SAVE**, read the trainer information, then **CHOOSE FILE / SAVE**. Pick a local Pokemon file or save that PKHeX supports, including extensionless saves such as `main`.
5. Review the added, already-imported, and refused counts. Conversion notes and up to 30 detailed warnings/refusals are displayed. One refused record does not prevent other records from being imported.

Your original file is read without being changed. Supported native records keep their native format. For other formats, PokeLDN chooses a compatible Bank format through its conversion rules. Imports use the configured trainer for each game. Games outside TradeBox's four trainer sections use the selected destination's trainer; its name and raw IDs are shown before choosing the file. This fills the complete seven-game trainer mapping required by PokeLDN's importer.

PokeLDN remembers imports even after a record has been traded away or deleted. Reimporting the same file can therefore report **Already imported** instead of creating another copy.

The browser gives most of the 800×480 screen to the Pokemon list, with compact rows and a wide touch scrollbar. Swipe the list or drag the scrollbar; **PREVIOUS** and **NEXT** move between pages of 12 records. Search and refresh share one toolbar. Tap a Pokemon row to see its full summary, legality, and conversion availability for the selected destination. Returning from details keeps your search, page, and scroll position. The browser also provides a **QUEUE** shortcut; import and destination controls stay on the Bank menu, reached with **BACK**. Conversion refusals and HOME tracker warnings are shown when reported by the API.

**DELETE BANK COPY** asks for confirmation and leaves the source file intact. Remove an entry from the queue before deleting it. A deleted entry can still be remembered as an earlier import.

## Queue and trade

1. Open a record with **VIEW**, check its destination, and choose **ADD TO QUEUE**.
2. Queue one to six different records. Open **QUEUE** to reorder or remove them. Removing a queued item keeps its Bank copy.
3. Choose **PREPARE TRADE**. PokeLDN converts each record for the selected game; the Bank copies remain in place. Any refused conversion prevents this run from starting.
4. Review the converted summaries and HOME tracker warnings, then choose **START TRADING** or **CANCEL**.
5. Follow the usual console instructions for the selected trade host. Sword/Shield uses the existing uncoded host; Z-A uses the launcher's default code `00000000`.

The queue belongs to the current app session. Bank records persist across restarts. After the queued Pokemon are exchanged, **keep the host running while the Switch finishes saving**, then exit trading on the Switch. In FR/LG, wait for the trade selection screen to return, then choose **CANCEL** and confirm **YES**. PokeLDN keeps the connection alive through the save and room-exit handshakes and closes after the Switch leaves. Do not start another trade once the queue is empty. Use **STOP** if you need to abort, or after leaving trading if the host remains running; stopping during the animation or save can prevent the Switch from retaining the received Pokemon. TradeBox drains the final completion lines before resetting the radio or starting a replacement host. Only completed slots leave the Bank; remaining slots stay queued while the app is open and their records remain in the Bank.

Banked records keep their identity: TradeBox never adds `--fresh-pid`. FR/LG uses explicit offered slots and the queue's trade count. A one-record FR/LG queue includes an unoffered filler because Direct Corner needs at least two host party members.

## Automatically bank received Pokemon

With API 1.4 available, Pokemon received from the retail game during **regular link trades and Bank queue trades** are automatically added to TradeBox's Bank. No import step is needed. **IMPORT FILE / SAVE** remains available for your other files and saves.

Each host receives a unique output prefix and log. Only files belonging to confirmed trade numbers are inspected with `SERVICE.check()` and copied through `bank.deposit()`. Merely offering a Pokemon, cancelling, or a successful process exit does not bank it. The original received bytes are preserved, including any legality warning reported by PKHeX; conversion checks still apply before trading it out. Identical bytes already held in the Bank do not create another copy.

Z-A, Sword/Shield, and BDSP can bank confirmed records while hosting. FR/LG received files are banked when PokeLDN writes them; final shutdown also collects any late files. Regular hosts retain their existing duration and trade behavior. A confirmed exchange is not a safe point to disconnect: Bank queue hosts stay connected while the Switch saves and exits trading.

Received files remain under `~/PokemonTradeBox/received-bank/`, with a unique prefix per run (relative to your actual TradeBox installation). Sword/Shield and BDSP's Received pages include these files. Existing files from older runs are left for manual import because they lack the new confirmation tracking.

Receipts record successful deposits per confirmed trade. Retrying progress, finishing, or reconciling an interrupted run does not re-bank its already processed files. If an inspection, deposit, or final received file is unavailable, TradeBox retains the run for **RETRY BANK FINISH**; it does not silently skip that Pokemon. A Bank progress/inspection failure leaves a running host connected so the Switch can finish saving and exit; retry Bank finish afterward. STOP continues to signal the exact host PID while Bank work stays off the UI thread.

## Storage and interrupted runs

The following local folders are excluded from Git updates:

| Folder | Contents |
| --- | --- |
| `bank/` | TradeBox's Bank records, maintained by PokeLDN's Bank API |
| `bank-data/` | Isolated helper output, prepared offers, and run receipts |
| `received-bank/` | Partner Pokemon files saved by regular and Bank trade hosts |
| `logs/` | Unique Bank host logs and `bank-worker.log` |

Back up these folders along with `config.json`. Do not point the desktop app at TradeBox's Bank folder. A worker holds an exclusive lock so two TradeBox workers cannot write it together.

An unfinished run appears in the Bank list after a worker interruption or restart. Stop its old host, then choose **RECONCILE FINISHED RUN**. Reconciliation uses that run's original ordered offers and confirmed completion lines; an exit code never proves a trade completed. It refuses to proceed while the recorded host is still alive and checks the Linux process identity to account for PID reuse. If startup was interrupted before a PID was recorded, the confirmation asks you to ensure no old host is running.

While a Bank run is active, imports, record changes, and queue changes are blocked. If completion processing fails (for example, because storage is not writable), the next radio action waits. Repair the cause, then choose **RETRY BANK FINISH** in the Bank. Repeated completion counts and retries are safe. Logs and receipts are retained for recovery. A missing/corrupt log or receipt must be repaired before that unfinished run can be reconciled.

**CANCEL BANK WORK** stops only the Bank worker and its own PKHeX helper. Imports can be partial; refresh the Bank afterwards. Preparing, cancelling, a process exit, and queued-trade messages do not remove Bank records. Trade launchers continue to use the existing exact-PID SIGINT / 15-second / SIGTERM shutdown contract.

## Pi validation and further checks

On 15 October 2026, Rick confirmed a one-record FR/LG Bank trade of Metapod completes the Switch's save, returns to trade selection, and exits through **CANCEL / YES**, with the received Metapod retained on the Switch. The run also handled an already-banked received Pokemon and closed the host cleanly after room exit. Pi file imports, duplicate recognition, the dedicated browser, and automatic received-Pokemon banking have also been checked.

The following checklist covers further regression scenarios, including save-file imports, partial/multiple queued trades, and other game destinations. Keep backup copies of the source Pokemon/save files used for testing.

1. Confirm Settings/startup checks recognize API 1.4 and open **POKEMON BANK**.
2. Import a known-good Pokemon file. Confirm the source file stays intact and the record appears. Import it again and check **Already imported**.
3. Import a small save, if available; check the result counts and browse/search the list.
4. Choose a compatible destination and queue one record. Prepare, then cancel. Confirm it remains in the Bank.
5. Prepare and complete one trade. After the received-Pokemon message, confirm the host stays connected through the save and the return to trade selection. Exit trading on the Switch (FR/LG: **CANCEL**, then **YES**). Confirm the host closes after departure, the outgoing Bank entry disappears, and the Pokemon sent from the retail game appears in Bank. Check the received Pokemon on the Switch after leaving the room.
6. Queue two records. Complete only the first, wait for saving and the return to trade selection, then exit on the Switch. Use STOP afterward if the host remains running. Confirm only the first outgoing Bank entry leaves, the second remains available, and only the confirmed received Pokemon is banked.
7. Test a multi-slot FR/LG queue if using that game, checking order and FireRed/LeafGreen selection.
8. Complete a normal builder link trade, wait for saving and the return to trade selection, then exit on the Switch. Use STOP afterward if the host remains running. Open Bank and verify the received retail Pokemon is present. Cancel a later trade before completion and confirm its offered Pokemon is absent.
9. Restart TradeBox and confirm the received Pokemon persists without duplicates. Check **IMPORT FILE / SAVE** and **CHECK BOARD** still work.

Automated coverage exercises stale callbacks, partial/final completion, skipped/repeated counts, conversion/import failures, worker timeouts/locks, recovery, host liveness through saving, and Bank pages at 800x480. The confirmed FR/LG hardware test supplements this coverage; the broader scenarios above remain available for further testing.
