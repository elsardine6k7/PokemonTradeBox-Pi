# Pokemon Bank

TradeBox v0.5.0 uses PokeLDN **v0.24.0+ / Program API 1.4** for Bank imports, records, conversions, and confirmed completion. The Bank runs in the configured PokeLDN venv; the touchscreen's system Python does not need the full desktop app's dependencies. The other TradeBox tools remain usable with API 1.3.

## Import and browse

1. Stop any host and wait for shutdown/reset to finish.
2. Open **POKEMON BANK** on Home. Choose **REFRESH** to load the records.
3. Choose **TRADE INTO** to select Z-A, Sword/Shield, BDSP, FireRed, or LeafGreen. Clear the queue before changing its destination.
4. Choose **IMPORT FILE / SAVE**, read the trainer information, then **CHOOSE FILE / SAVE**. Pick a local Pokemon file or save that PKHeX supports, including extensionless saves such as `main`.
5. Review the added, already-imported, and refused counts. Conversion notes and up to 30 detailed warnings/refusals are displayed. One refused record does not prevent other records from being imported.

Your original file is read without being changed. Supported native records keep their native format. For other formats, PokeLDN chooses a compatible Bank format through its conversion rules. Imports use the configured trainer for each game. Games outside TradeBox's four trainer sections use the selected destination's trainer; its name and raw IDs are shown before choosing the file. This fills the complete seven-game trainer mapping required by PokeLDN's importer.

PokeLDN remembers imports even after a record has been traded away or deleted. Reimporting the same file can therefore report **Already imported** instead of creating another copy.

The list shows 12 records per page. Type a search and tap **SEARCH** (or press Enter). **VIEW** shows the original summary, legality, and conversion availability for the selected destination. Conversion refusals and HOME tracker warnings are shown when reported by the API.

**DELETE BANK COPY** asks for confirmation and leaves the source file intact. Remove an entry from the queue before deleting it. A deleted entry can still be remembered as an earlier import.

## Queue and trade

1. Open a record with **VIEW**, check its destination, and choose **ADD TO QUEUE**.
2. Queue one to six different records. Open **QUEUE** to reorder or remove them. Removing a queued item keeps its Bank copy.
3. Choose **PREPARE TRADE**. PokeLDN converts each record for the selected game; the Bank copies remain in place. Any refused conversion prevents this run from starting.
4. Review the converted summaries and HOME tracker warnings, then choose **START TRADING** or **CANCEL**.
5. Follow the usual console instructions for the selected trade host. Sword/Shield uses the existing uncoded host; Z-A uses the launcher's default code `00000000`.

The queue belongs to the current app session. Bank records persist across restarts. The host is stopped when all queued trades are confirmed; you can also use **STOP** at any point. TradeBox drains the final completion lines before resetting the radio or starting a replacement host. Only completed slots leave the Bank; remaining slots stay queued while the app is open and their records remain in the Bank.

Banked records keep their identity: TradeBox never adds `--fresh-pid`. FR/LG uses explicit offered slots and the queue's trade count. A one-record FR/LG queue includes an unoffered filler because Direct Corner needs at least two host party members.

Partner Pokemon files are saved under `~/PokemonTradeBox/received-bank/`, with a unique prefix per run (relative to your actual TradeBox installation). Use the import dialog to bank a received file later. TradeBox does not automatically import every saved offer, since a host can write a partner's offered record before that trade is confirmed.

## Storage and interrupted runs

The following local folders are excluded from Git updates:

| Folder | Contents |
| --- | --- |
| `bank/` | TradeBox's Bank records, maintained by PokeLDN's Bank API |
| `bank-data/` | Isolated helper output, prepared offers, and run receipts |
| `received-bank/` | Partner Pokemon files saved by Bank hosts |
| `logs/` | Unique Bank host logs and `bank-worker.log` |

Back up these folders along with `config.json`. Do not point the desktop app at TradeBox's Bank folder. A worker holds an exclusive lock so two TradeBox workers cannot write it together.

An unfinished run appears in the Bank list after a worker interruption or restart. Stop its old host, then choose **RECONCILE FINISHED RUN**. Reconciliation uses that run's original ordered offers and confirmed completion lines; an exit code never proves a trade completed. It refuses to proceed while the recorded host is still alive and checks the Linux process identity to account for PID reuse. If startup was interrupted before a PID was recorded, the confirmation asks you to ensure no old host is running.

While a Bank run is active, imports, record changes, and queue changes are blocked. If completion processing fails (for example, because storage is not writable), the next radio action waits. Repair the cause, then choose **RETRY BANK FINISH** in the Bank. Repeated completion counts and retries are safe. Logs and receipts are retained for recovery. A missing/corrupt log or receipt must be repaired before that unfinished run can be reconciled.

**CANCEL BANK WORK** stops only the Bank worker and its own PKHeX helper. Imports can be partial; refresh the Bank afterwards. Preparing, cancelling, a process exit, and queued-trade messages do not remove Bank records. Trade launchers continue to use the existing exact-PID SIGINT / 15-second / SIGTERM shutdown contract.

## Pi test checklist (pending)

Keep backup copies of the source Pokemon/save files used for testing.

1. Confirm Settings/startup checks recognize API 1.4 and open **POKEMON BANK**.
2. Import a known-good Pokemon file. Confirm the source file stays intact and the record appears. Import it again and check **Already imported**.
3. Import a small save, if available; check the result counts and browse/search the list.
4. Choose a compatible destination and queue one record. Prepare, then cancel. Confirm it remains in the Bank.
5. Prepare and complete one trade. Confirm the console receives it, the host stops, and the Bank entry disappears after confirmation.
6. Queue two records. Complete only the first, then STOP. Confirm only the first Bank entry leaves and the second remains available.
7. Test a multi-slot FR/LG queue if using that game, checking order and FireRed/LeafGreen selection.
8. Reconnect and test a normal non-Bank trade and STOP, plus **CHECK BOARD**.

Automated coverage exercises stale callbacks, partial/final completion, skipped/repeated counts, conversion/import failures, worker timeouts/locks, recovery, and Bank pages at 800x480. Console behavior still needs this hardware check before merging.
