"""Render the real GTK Bank pages at 800x480 under Xvfb; no backend or radio."""
import copy
import sys
import time
from pathlib import Path


def main():
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk, GLib

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from tradebox import TradeBox
    from startup_checks import DEFAULT_CONFIG

    Gtk.init()
    app = TradeBox()
    app.register(None)
    app.win = Gtk.ApplicationWindow(application=app)
    app.win.set_decorated(False)
    app.win.set_default_size(800, 480)
    app._install_touch_scrollbar_css()
    app._backend_ready = app._bank_available = True
    app._bank_config = copy.deepcopy(DEFAULT_CONFIG)
    app._host_prerequisites = lambda _cmd: True
    entries = [{"id": str(n), "summary": f"Pokemon {n}, level 100, Timid, Ability, held item, four moves",
                "game": "swsh", "legal": True, "home_tracker": ""} for n in range(1000)]
    app.bank_entries = entries

    def rpc(action, payload, callback, **_kwargs):
        if action == "details":
            result = {"entry": entries[0], "route": {"ok": True, "home_tracker": "empty"}}
        elif action == "import":
            result = {"name": "main", "save": "Sword, RICK", "counts": {"banked": 1, "already": 1, "refused": 1},
                      "details": [{"where": "Box 1", "species": "Pokemon", "state": "refused", "detail": "Refused conversion"}]}
        elif action == "begin":
            result = {"cmd": ["host"], "offers": [{"bank": item["id"], "file": "offer",
                "summary": item["summary"], "home_tracker": "empty"} for item in app.bank_queue]}
        elif action == "end":
            result = {"token": payload["token"], "completed": 0, "total": len(app.bank_queue)}
        else:
            result = {"entries": entries, "pending": []}
        GLib.idle_add(callback, result, "")
    app._bank_rpc = rpc

    def check(name, expected_title):
        app.win.present()
        context = GLib.MainContext.default()
        deadline = time.monotonic() + 3
        stable = 0
        while time.monotonic() < deadline:
            while context.pending():
                context.iteration(False)
            root = app.win.get_child()
            scrolled = []
            def walk(widget):
                if isinstance(widget, Gtk.ScrolledWindow) and widget.get_visible():
                    scrolled.append(widget.get_height())
                child = widget.get_first_child()
                while child is not None:
                    walk(child)
                    child = child.get_next_sibling()
            walk(root)
            ready = (root.get_mapped() and app._current_page_title.startswith(expected_title)
                     and all(height >= 60 for height in scrolled))
            stable = stable + 1 if ready else 0
            if stable >= 3:
                break
            time.sleep(.02)
        width, height = app.win.get_width(), app.win.get_height()
        if not app._current_page_title.startswith(expected_title):
            raise AssertionError(f"{name} did not open: {app._current_page_title}")
        if width > 800 or height > 480:
            raise AssertionError(f"{name} forces a {width}x{height} window")
        if scrolled and min(scrolled) < 60:
            raise AssertionError(f"{name} leaves too little scrolling space: {scrolled}; root={root.get_width()}x{root.get_height()}, mapped={root.get_mapped()}")
        print(f"OK: {name}, {width}x{height}, scroll={scrolled}")

    app.show_home()
    check("Home", "POK")
    app.show_bank()
    check("Bank with 1000 records", "POKEMON BANK")
    app.bank_choose_game()
    check("Game selection", "BANK DESTINATION")
    app.bank_choose_import()
    check("Import trainer confirmation", "BANK IMPORT")
    app.bank_import("main")
    check("Import results", "IMPORT RESULTS")
    app.bank_details(entries[0])
    check("Record and conversion details", "BANK POKEMON")
    app.bank_confirm_remove(entries[0])
    check("Deletion confirmation", "DELETE BANK COPY")
    app.bank_queue = entries[:6]
    app.show_bank_queue()
    check("Six-slot queue", "BANK QUEUE")
    app.bank_prepare_trade()
    check("Converted offer confirmation", "CONFIRM BANK TRADE")
    app.show_bank_queue()
    check("Prepared queue and cancellation controls", "BANK QUEUE")
    app.bank_cancel_prepared()
    check("Cancelled queue", "BANK QUEUE")
    app.bank_pending = [{"token": "c" * 32, "game": "za", "pid": None, "live": False}]
    app.show_bank()
    check("Unfinished run", "POKEMON BANK")
    app.bank_confirm_recover(app.bank_pending[0])
    check("Recovery confirmation", "RECONCILE BANK RUN")
    app.win.destroy()
    app.quit()


if __name__ == "__main__":
    main()
