"""Read-only startup diagnostics, shared by the touchscreen and installer.

The PKHeX health request runs in a bounded child process. Checks never open the
serial port, reset a board, load user plugins, or read the contents of prod.keys.
"""
from __future__ import annotations

import argparse
import copy
import importlib
import json
import os
import re
import signal
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path


DEFAULT_CONFIG = {
    "pokeldn_repo": "~/pokeldn",
    "prod_keys": "~/.switch/prod.keys",
    "radio": "auto",
    "frlg_version": "firered",
    "trainers": {
        game: {"ot": "PLAYER", "tid": 0, "sid": 0, "language": 2, "gender": 0}
        for game in ("za", "swsh", "bdsp", "frlg")
    },
}


class ConfigError(ValueError):
    pass


def config_path(app_dir: Path) -> Path:
    return Path(os.environ.get("POKEMON_TRADEBOX_CONFIG", str(app_dir / "config.json"))).expanduser().resolve()


def _text(value, label):
    if not isinstance(value, str) or not value.strip() or any(ord(c) < 32 for c in value):
        raise ConfigError(f"{label} must be a non-empty text value without control characters.")
    return value.strip()


def load_config(path: Path) -> dict:
    try:
        user = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ConfigError(f"Config not found: {path}. Copy config.example.json here and enter your settings.") from None
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Invalid JSON in {path.name}, line {exc.lineno}, column {exc.colno}. Fix the file, then tap Retry.") from None
    except (OSError, UnicodeError):
        raise ConfigError(f"Cannot read {path}. Check its permissions and UTF-8 encoding.") from None
    if not isinstance(user, dict):
        raise ConfigError("The config must be a JSON object.")
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    for key in ("pokeldn_repo", "prod_keys", "radio", "frlg_version"):
        if key in user:
            cfg[key] = _text(user[key], key)
    cfg["frlg_version"] = cfg["frlg_version"].lower()
    if cfg["frlg_version"] not in ("firered", "leafgreen"):
        raise ConfigError("frlg_version must be firered or leafgreen.")
    radio = cfg["radio"].removeprefix("esp32:")
    if not radio or (radio != "auto" and ":" in radio):
        raise ConfigError("radio must be auto, esp32:auto, or an ESP32 serial-device path.")
    for key in ("pokeldn_repo", "prod_keys"):
        value = Path(cfg[key]).expanduser()
        cfg[key] = str(value if value.is_absolute() else (path.parent / value).resolve())
    if radio != "auto":
        value = Path(radio).expanduser()
        cfg["radio"] = "esp32:" + str(value if value.is_absolute() else (path.parent / value).resolve())
    trainers = user.get("trainers", {})
    if not isinstance(trainers, dict):
        raise ConfigError("trainers must be a JSON object.")
    for game, trainer in cfg["trainers"].items():
        supplied = trainers.get(game, {})
        if not isinstance(supplied, dict):
            raise ConfigError(f"trainers.{game} must be a JSON object.")
        trainer.update(supplied)
        trainer["ot"] = _text(trainer["ot"], f"trainers.{game}.ot")
        for key, maximum in (("tid", 65535), ("sid", 65535), ("gender", 1)):
            value = trainer[key]
            if type(value) is not int or not 0 <= value <= maximum:
                raise ConfigError(f"trainers.{game}.{key} must be an integer from 0 to {maximum}.")
        languages = (1, 2, 3, 4, 5, 7) if game == "frlg" else (1, 2, 3, 4, 5, 7, 8, 9, 10)
        if type(trainer["language"]) is not int or trainer["language"] not in languages:
            raise ConfigError(f"trainers.{game}.language must be one of {', '.join(map(str, languages))}.")
    return cfg


def find_radio(radio: str, dev_root: Path = Path("/dev")) -> Path | None:
    raw = radio.removeprefix("esp32:")
    if raw != "auto":
        path = Path(raw).expanduser()
        return path if path.exists() else None
    candidates = sorted(p for p in (dev_root / "serial" / "by-id").glob("*") if p.exists())
    preferred = [p for p in candidates if any(token in p.name.casefold()
                 for token in ("cp210", "silicon_labs", "usb_to_uart"))]
    if preferred or candidates:
        return (preferred or candidates)[0]
    for name in ("ttyUSB0", "ttyACM0"):
        path = dev_root / name
        if path.exists():
            return path
    return None


def key_problem(path: Path) -> str:
    try:
        if path.is_file() and path.stat().st_size > 0 and os.access(path, os.R_OK):
            return ""
    except OSError:
        pass
    return f"Keys missing, empty, or unreadable: {path}. Set prod_keys in config.json."


def radio_problem(radio: str) -> str:
    port = find_radio(radio)
    if port is None:
        return "ESP32 not found. Connect it or correct the radio setting; team editing is available offline."
    if not os.access(port, os.R_OK | os.W_OK):
        return f"ESP32 port is not readable/writable: {port}. Check the Pi user's serial permissions."
    return ""


@dataclass
class Check:
    label: str
    state: str
    detail: str


@dataclass
class StartupReport:
    config: dict | None = None
    checks: list[Check] = field(default_factory=list)
    species: dict[str, int] = field(default_factory=dict)
    version: str = "Unknown"
    api: str = "Unknown"
    serial_ready: bool = False
    firmware_ready: bool = False
    bank_ready: bool = False

    @property
    def ready(self):
        return self.config is not None and not any(c.state == "error" for c in self.checks)

    @property
    def warnings(self):
        return any(c.state == "warning" for c in self.checks)

    def text(self):
        return "\n\n".join(f"{c.state.upper()} - {c.label}\n{c.detail}" for c in self.checks)


# Only the documented Program Surface is inspected. Importing API metadata does
# not discover, enable, or register user plugins.
SURFACE = {
    "pokeldn.pokemon": ("BuilderError", "NATURES", "SERVICE.species", "SERVICE.names", "SERVICE.options", "SERVICE.make", "SERVICE.paste"),
    "pokeldn.gifts": ("load", "save"),
    "pokeldn.swsh.gift_builder": ("KINDS", "PRESETS", "PRESET", "OUTFITS", "blank", "compile", "describe"),
    "pokeldn.swsh.events": ("load", "by_key", "gift"),
    "pokeldn.frlg.gift.builder": ("KINDS", "PRESETS", "PRESET", "GIVERS", "CARTRIDGES", "blank", "compile", "describe"),
}
BOARD_SURFACE = ("ports", "identify", "detect_chip", "download_firmware", "image_for", "image_version", "flash")


def _surface(module_name, names):
    module = importlib.import_module(module_name)
    for name in names:
        obj = module
        for part in name.split("."):
            obj = getattr(obj, part)
        if obj is None:
            raise ValueError(f"Missing supported name: {module_name}.{name}")
        if not name.isupper() and not name.endswith("Error") and not callable(obj):
            raise ValueError(f"Supported function is not callable: {module_name}.{name}")


def probe_backend(repo: Path, *, pkhex: bool) -> dict:
    sys.path.insert(0, str(repo))
    result = {"ok": False, "serial_ready": False, "firmware_ready": False}
    try:
        pokeldn = importlib.import_module("pokeldn")
        if Path(pokeldn.__file__).resolve().parent.parent != repo.resolve():
            raise ValueError("Python imported a different PokeLDN checkout. Check pokeldn_repo.")
        version = str(getattr(pokeldn, "__version__", "Unknown"))
        match = re.match(r"^(\d+)\.(\d+)\.(\d+)", version)
        if not match or tuple(map(int, match.groups())) < (0, 23, 0):
            raise ValueError(f"PokeLDN {version} is unsupported. Install v0.23.0 or newer.")
        # API metadata imports the full tool catalog and its radio/game
        # dependencies. Validate it in the backend venv; the touchscreen uses
        # this same checkout, but only imports the builder surface below.
        if pkhex:
            api = importlib.import_module("pokeldn.plugins").API
            if api.version != 1 or api.level < 3:
                raise ValueError(f"Program Surface {api.version}.{api.level} is unsupported. TradeBox requires API major 1, level 3 or newer.")
            result["api"] = f"{api.version}.{api.level}"
        for module, names in SURFACE.items():
            _surface(module, names)
        result.update(ok=True, version=version)
        if pkhex and api.level >= 4:
            try:
                _surface("pokeldn.app.bank", ("entries", "find", "import_file", "destinations", "offer", "remove", "TradeSession", "TradeSession.advance"))
                _surface("pokeldn.app.received", ("trades_done",))
                result["bank_ready"] = True
            except Exception as exc:
                result["bank_warning"] = f"Bank API unavailable: {exc}. Check your PokeLDN v0.24.0+ installation."
    except Exception as exc:
        result["error"] = f"PokeLDN import/API check failed ({type(exc).__name__}): {exc}"
        return result
    try:
        importlib.import_module("serial")
        result["serial_ready"] = True
    except Exception:
        result["serial_warning"] = "Python cannot import pyserial. Install python3-serial for the touchscreen, and pyserial in the PokeLDN venv."
    if pkhex:
        try:
            _surface("gui.board", BOARD_SURFACE)
            importlib.import_module("esptool")
            result["firmware_ready"] = True
        except Exception as exc:
            result["firmware_warning"] = f"ESP32 firmware tools unavailable: {exc}. Check the PokeLDN venv; install esptool==5.4.0 there."
        try:
            service = importlib.import_module("pokeldn.pokemon").SERVICE
            counts = {game: len(service.species(game)) for game in ("frlg", "swsh", "bdsp", "za")}
            if not all(counts.values()):
                raise ValueError("A required species catalog was empty.")
            result["species"] = counts
        except Exception as exc:
            result.update(ok=False, error=f"PKHeX check failed: {exc}. Check its build/runtime, then tap Retry.")
    return result


def run_probe(python: Path, repo: Path, *, pkhex: bool, timeout=None) -> dict:
    cmd = [str(python), str(Path(__file__).resolve()), "--probe", str(repo)]
    if pkhex:
        cmd.append("--pkhex")
    # Only this diagnostic and the helper it starts enter this process group.
    # Launcher STOP still signals the exact launcher PID via SessionControl.
    proc = subprocess.Popen(cmd, cwd=repo, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, encoding="utf-8", start_new_session=os.name == "posix")
    try:
        output, _stderr = proc.communicate(timeout=timeout if timeout is not None else (25 if pkhex else 10))
    except subprocess.TimeoutExpired:
        if os.name == "posix":
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        else:
            proc.terminate()
        try:
            proc.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            if os.name == "posix":
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            else:
                proc.kill()
            proc.communicate()
        return {"ok": False, "error": "PokeLDN/PKHeX check timed out. Check its installation, then tap Retry."}
    try:
        result = json.loads(output)
        if not isinstance(result, dict) or type(result.get("ok")) is not bool:
            raise ValueError("Invalid diagnostic response")
        return result
    except (ValueError, TypeError):
        return {"ok": False, "error": f"Diagnostic Python exited with code {proc.returncode} without a valid response. Check the PokeLDN venv and Python version."}


def check_startup(path: Path, app_dir: Path, *, runner=run_probe, frontend_python=None) -> StartupReport:
    report = StartupReport()
    try:
        report.config = cfg = load_config(path)
    except ConfigError as exc:
        report.checks.append(Check("Configuration", "error", str(exc)))
        return report
    report.checks.append(Check("Configuration", "ok", f"Loaded {path}; trainer values are valid raw TID/SID pairs."))
    repo = Path(cfg["pokeldn_repo"])
    python = repo / ".venv" / "bin" / "python"
    if not (repo / "pokeldn" / "__init__.py").is_file():
        report.checks.append(Check("PokeLDN checkout", "error", f"Not found at {repo}. Set pokeldn_repo to your source checkout."))
    elif not python.is_file() or not os.access(python, os.X_OK):
        report.checks.append(Check("PokeLDN venv", "error", f"Python not executable at {python}. Install PokeLDN's virtual environment."))
    else:
        venv_serial_ready = False
        for label, executable, pkhex in (("PokeLDN venv / PKHeX", python, True),
                                        ("Touchscreen Python", Path(frontend_python or sys.executable), False)):
            try:
                result = runner(executable, repo, pkhex=pkhex)
            except (OSError, ValueError) as exc:
                result = {"ok": False, "error": f"Cannot run diagnostic: {exc}"}
            if result["ok"]:
                detail = f"PokeLDN {result.get('version')}, API {result.get('api')}" if pkhex else (
                    f"PokeLDN {result.get('version')}; required builders imported successfully.")
            else:
                detail = result["error"]
            report.checks.append(Check(label, "ok" if result["ok"] else "error", detail))
            if pkhex:
                venv_serial_ready = result.get("serial_ready", False)
                report.version = result.get("version", "Unknown")
                report.api = result.get("api", "Unknown")
                report.species = result.get("species", {})
                report.firmware_ready = result.get("firmware_ready", False)
                report.bank_ready = result.get("bank_ready", False)
                if result.get("bank_warning"):
                    report.checks.append(Check("Bank API", "warning", result["bank_warning"]))
                if result.get("firmware_warning"):
                    report.checks.append(Check("Firmware tools", "warning", result["firmware_warning"]))
            else:
                report.serial_ready = venv_serial_ready and result.get("serial_ready", False)
            if result.get("serial_warning"):
                report.checks.append(Check(label + " serial tools", "warning", result["serial_warning"]))
    for label, problem in (("Console keys", key_problem(Path(cfg["prod_keys"]))),
                           ("ESP32 connection", radio_problem(cfg["radio"]))):
        report.checks.append(Check(label, "warning" if problem else "ok", problem or "Available (not opened)."))
    try:
        for folder in (app_dir / "logs", app_dir / "gifts"):
            folder.mkdir(parents=True, exist_ok=True)
            if not os.access(folder, os.W_OK):
                raise OSError(f"{folder} is not writable")
    except OSError as exc:
        report.checks.append(Check("Local storage", "error", f"Cannot use logs/gifts: {exc}. Check folder permissions."))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--frontend-python", type=Path, help="Python used by the touchscreen launcher")
    parser.add_argument("--probe", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--pkhex", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.probe:
        # Interrupt a stuck SERVICE.species request before the parent timeout;
        # normal interpreter exit runs PokeLDN's own exact-helper cleanup.
        def timed_out(_signum, _frame):
            raise TimeoutError("PKHeX did not respond within 20 seconds")
        if hasattr(signal, "SIGALRM"):
            signal.signal(signal.SIGALRM, timed_out)
            signal.alarm(20 if args.pkhex else 8)
        from contextlib import redirect_stdout
        with redirect_stdout(sys.stderr):
            result = probe_backend(args.probe, pkhex=args.pkhex)
        if hasattr(signal, "SIGALRM"):
            signal.alarm(0)
        print(json.dumps(result))
        return 0 if result["ok"] else 1
    app_dir = Path(__file__).resolve().parent
    report = check_startup((args.config or config_path(app_dir)).expanduser().resolve(), app_dir,
                           frontend_python=args.frontend_python)
    print(report.text())
    return 0 if report.ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
