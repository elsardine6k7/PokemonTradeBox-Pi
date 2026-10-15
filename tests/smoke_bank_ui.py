"""Render real GTK Bank pages at 800x480 on a test display; no backend/radio."""
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
            result = {"entry": next(entry for entry in entries if entry["id"] == payload["id"]),
                      "route": {"ok": True, "home_tracker": "empty"}}
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

    def widgets():
        result = []
        def walk(widget):
            if widget.get_visible():
                result.append(widget)
            child = widget.get_first_child()
            while child is not None:
                walk(child)
                child = child.get_next_sibling()
        walk(app.win.get_child())
        return result

    def buttons(label):
        return [widget for widget in widgets()
                if isinstance(widget, Gtk.Button) and widget.get_label() == label]

    def click(label):
        matches = buttons(label)
        if len(matches) != 1 or not matches[0].get_sensitive():
            raise AssertionError(f"Expected one enabled {label!r} button, got {matches}")
        matches[0].emit("clicked")

    def browser_scroller():
        return next(widget for widget in widgets() if isinstance(widget, Gtk.ScrolledWindow))

    def record_buttons():
        result = []
        column = browser_scroller().get_child()
        if isinstance(column, Gtk.Viewport):
            column = column.get_child()
        child = column.get_first_child()
        while child is not None:
            if isinstance(child, Gtk.Button):
                result.append(child)
            child = child.get_next_sibling()
        return result

    def check(name, expected_title, min_scroll=60):
        app.win.present()
        context = GLib.MainContext.default()
        deadline = time.monotonic() + 3
        stable = 0
        while time.monotonic() < deadline:
            while context.pending():
                context.iteration(False)
            root = app.win.get_child()
            scrolled = [widget.get_height() for widget in widgets()
                        if isinstance(widget, Gtk.ScrolledWindow)]
            ready = (root.get_mapped() and app._current_page_title.startswith(expected_title)
                     and all(height >= min_scroll for height in scrolled))
            stable = stable + 1 if ready else 0
            if stable >= 3:
                break
            time.sleep(.02)
        width, height = app.win.get_width(), app.win.get_height()
        if not app._current_page_title.startswith(expected_title):
            raise AssertionError(f"{name} did not open: {app._current_page_title}")
        if not root.get_mapped():
            raise AssertionError(f"{name} was not mapped on the test display")
        if width > 800 or height > 480:
            raise AssertionError(f"{name} forces a {width}x{height} window")
        if scrolled and min(scrolled) < min_scroll:
            raise AssertionError(f"{name} leaves too little scrolling space: {scrolled}; root={root.get_width()}x{root.get_height()}, mapped={root.get_mapped()}")
        print(f"OK: {name}, {width}x{height}, scroll={scrolled}")

    app.show_home()
    check("Home", "POK")
    app.show_bank()
    check("Bank menu with 1000 records", "POKEMON BANK")
    if any(isinstance(widget, Gtk.Entry) for widget in widgets()):
        raise AssertionError("The Bank menu still contains the crowded record browser")
    browse = next(widget for widget in widgets()
                  if isinstance(widget, Gtk.Button) and widget.get_label().startswith("BROWSE POKEMON"))
    browse.emit("clicked")
    check("Dedicated Pokemon browser", "BANK BROWSER", min_scroll=230)
    if len(record_buttons()) != 12 or buttons("IMPORT FILE / SAVE"):
        raise AssertionError("The browser must show a record page without import controls")
    # get_height() excludes CSS padding/borders; the full allocation is the
    # touchscreen target that the parent gives each button.
    row_heights = [button.get_allocation().height for button in record_buttons()]
    if min(row_heights) < 44:
        raise AssertionError(f"Pokemon rows need touchscreen-sized controls: allocated heights={row_heights}")
    print(f"OK: Pokemon touch targets, height={min(row_heights)}")
    click("NEXT")
    check("Second record page", "BANK BROWSER", min_scroll=230)
    if app.bank_page != 1:
        raise AssertionError("Next did not advance the Pokemon page")
    adjustment = browser_scroller().get_vadjustment()
    scroll = min(150, adjustment.get_upper() - adjustment.get_page_size())
    if scroll <= 0:
        raise AssertionError("The Pokemon list should scroll independently of navigation")
    adjustment.set_value(scroll)
    previous_status = app.current_label
    app.set_status("Bank status: " + "Received Pokemon added to the Bank. " * 3)
    check("Browser after status changes height", "BANK BROWSER", min_scroll=230)
    if abs(browser_scroller().get_vadjustment().get_value() - scroll) > 2:
        raise AssertionError("A status resize reset the user's scrolling position")
    app.set_status(previous_status)
    check("Browser after status returns", "BANK BROWSER", min_scroll=230)
    app.bank_details(entries[12])
    check("Record and conversion details", "BANK POKEMON")
    click("← BACK")
    check("Details return to browser", "BANK BROWSER", min_scroll=230)
    if app.bank_page != 1 or abs(browser_scroller().get_vadjustment().get_value() - scroll) > 2:
        raise AssertionError("Returning from details lost the page or scroll position")
    click("REFRESH")
    check("Refresh stays in browser", "BANK BROWSER", min_scroll=230)
    if app.bank_page != 1:
        raise AssertionError("Refresh lost the selected Pokemon page")
    search = next(widget for widget in widgets() if isinstance(widget, Gtk.Entry))
    search.set_text("Pokemon 998,")
    click("SEARCH")
    check("Search stays in browser", "BANK BROWSER", min_scroll=230)
    if app.bank_page != 0 or len(record_buttons()) != 1:
        raise AssertionError("Search did not reset the page and filter the Pokemon")
    search = next(widget for widget in widgets() if isinstance(widget, Gtk.Entry))
    search.set_text("")
    search.emit("activate")
    check("Search entry activation", "BANK BROWSER", min_scroll=230)
    click("← BACK")
    check("Browser returns to Bank menu", "POKEMON BANK")
    app.bank_choose_game()
    check("Game selection", "BANK DESTINATION")
    app.bank_choose_import()
    check("Import trainer confirmation", "BANK IMPORT")
    app.bank_import("main")
    check("Import results", "IMPORT RESULTS")
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
    if not buttons("RECONCILE FINISHED RUN"):
        raise AssertionError("Unfinished-run recovery is no longer reachable from the Bank menu")
    app.bank_confirm_recover(app.bank_pending[0])
    check("Recovery confirmation", "RECONCILE BANK RUN")
    app._bank_busy, app._bank_cancel_allowed = True, True
    app.show_bank_browser()
    check("Browser during Bank work", "BANK BROWSER", min_scroll=230)
    if any(button.get_sensitive() for button in record_buttons()):
        raise AssertionError("Busy Bank record actions should be disabled")
    click("← BACK")
    check("Bank work cancellation remains reachable", "POKEMON BANK")
    if not buttons("CANCEL BANK WORK") or not buttons("CANCEL BANK WORK")[0].get_sensitive():
        raise AssertionError("Bank work cancellation is unavailable")
    app._bank_busy, app._bank_cancel_allowed = False, False
    app.win.destroy()
    app.quit()


if __name__ == "__main__":
    main()
