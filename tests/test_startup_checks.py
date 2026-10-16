"""Configuration, backend failure, timeout, and installer behavior without hardware."""
import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from startup_checks import (
    BOARD_SURFACE, DEFAULT_CONFIG, SURFACE, ConfigError,
    check_startup, config_path, find_radio, load_config, run_probe,
)


def fake_backend(repo, *, version="0.23.0", api=(1, 3), service=None):
    """A standalone fake Program Surface for real child-process checks."""
    repo.mkdir(parents=True, exist_ok=True)
    for name in SURFACE:
        path = repo.joinpath(*name.split(".")).with_suffix(".py")
        path.parent.mkdir(parents=True, exist_ok=True)
        for folder in path.parents:
            if folder == repo:
                break
            (folder / "__init__.py").touch()
        lines = []
        for attr in SURFACE[name]:
            if "." in attr:
                continue
            if attr == "BuilderError":
                lines.append("class BuilderError(Exception): pass")
            elif attr.isupper():
                lines.append(f"{attr} = {{}}")
            else:
                lines.append(f"def {attr}(*a, **kw): return None")
        if name == "pokeldn.pokemon":
            lines.append(service or (
                "class Service:\n"
                "    def species(self, game): return [game]\n"
                "    names = options = make = paste = check = species\n"
                "SERVICE = Service()"))
        path.write_text("\n".join(lines), encoding="utf-8")
    (repo / "pokeldn" / "__init__.py").write_text(f"__version__ = {version!r}", encoding="utf-8")
    (repo / "pokeldn" / "plugins.py").write_text(
        f"class API:\n    version = {api[0]}\n    level = {api[1]}\n", encoding="utf-8")
    (repo / "serial.py").touch()
    (repo / "esptool.py").touch()
    (repo / "gui").mkdir(exist_ok=True)
    (repo / "gui" / "__init__.py").touch()
    (repo / "gui" / "board.py").write_text(
        "\n".join(f"def {name}(*a, **kw): pass" for name in BOARD_SURFACE), encoding="utf-8")
    python = repo / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True, exist_ok=True)
    if os.name == "posix":
        python.symlink_to(sys.executable)
    else:
        python.touch()


class StartupChecksTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.path = self.root / "config.json"
        self.cfg = copy.deepcopy(DEFAULT_CONFIG)
        self.cfg["pokeldn_repo"] = str(self.root / "custom-pokeldn")
        self.cfg["prod_keys"] = str(self.root / "custom.keys")
        self.write_config()

    def write_config(self):
        self.path.write_text(json.dumps(self.cfg), encoding="utf-8")

    def test_bad_json_and_wrong_shapes_have_actionable_errors(self):
        for content, message in (("{\n broken", "line 2"), ("[]", "JSON object"),
                                 ('{"trainers":null}', "trainers must"),
                                 ('{"pokeldn_repo":12}', "pokeldn_repo must")):
            with self.subTest(content=content):
                self.path.write_text(content, encoding="utf-8")
                report = check_startup(self.path, self.root)
                self.assertFalse(report.ready)
                self.assertIn(message, report.text())

    def test_trainer_ids_are_raw_16_bit_integers_and_invalid_fields_are_rejected(self):
        for key, value in (("tid", 65536), ("sid", -1), ("tid", True), ("sid", "123"),
                           ("gender", 2), ("language", 6), ("ot", "")):
            with self.subTest(key=key, value=value):
                cfg = copy.deepcopy(self.cfg)
                cfg["trainers"]["frlg"][key] = value
                self.path.write_text(json.dumps(cfg), encoding="utf-8")
                with self.assertRaisesRegex(ConfigError, f"trainers.frlg.{key}"):
                    load_config(self.path)
        self.cfg["trainers"]["frlg"].update(tid=65535, sid=0, language=7, gender=1)
        self.write_config()
        self.assertEqual(load_config(self.path)["trainers"]["frlg"]["tid"], 65535)

    def test_partial_old_config_keeps_defaults_and_resolves_paths_from_config_folder(self):
        self.path.write_text(json.dumps({"pokeldn_repo": "backend", "prod_keys": "keys",
                                        "trainers": {"swsh": {"ot": "RICK"}}}), encoding="utf-8")
        cfg = load_config(self.path)
        self.assertEqual(cfg["pokeldn_repo"], str(self.root / "backend"))
        self.assertEqual(cfg["prod_keys"], str(self.root / "keys"))
        self.assertEqual(cfg["trainers"]["swsh"]["ot"], "RICK")
        self.assertEqual(cfg["trainers"]["bdsp"], DEFAULT_CONFIG["trainers"]["bdsp"])
        self.assertEqual(DEFAULT_CONFIG["trainers"]["swsh"]["ot"], "PLAYER")
        with patch.dict(os.environ, {"POKEMON_TRADEBOX_CONFIG": str(self.path)}):
            self.assertEqual(config_path(self.root / "elsewhere"), self.path)

    def test_invalid_radio_and_game_selection_are_config_errors(self):
        for key, value in (("radio", "esp32:"), ("radio", "wifi:auto"),
                           ("frlg_version", "emerald")):
            with self.subTest(key=key):
                cfg = dict(self.cfg, **{key: value})
                self.path.write_text(json.dumps(cfg), encoding="utf-8")
                with self.assertRaises(ConfigError):
                    load_config(self.path)

    def test_missing_checkout_and_venv_stop_before_running_any_diagnostic(self):
        calls = []
        runner = lambda *a, **k: calls.append(a)
        report = check_startup(self.path, self.root, runner=runner)
        self.assertFalse(report.ready)
        self.assertIn("PokeLDN checkout", report.text())
        init = Path(self.cfg["pokeldn_repo"]) / "pokeldn" / "__init__.py"
        init.parent.mkdir(parents=True)
        init.touch()
        report = check_startup(self.path, self.root, runner=runner)
        self.assertFalse(report.ready)
        self.assertIn("venv", report.text())
        self.assertEqual(calls, [])

    def test_missing_keys_and_radio_allow_builders_and_config_is_never_rewritten(self):
        fake_backend(Path(self.cfg["pokeldn_repo"]))
        before = self.path.read_bytes()
        calls = []
        def runner(python, repo, *, pkhex):
            calls.append((python, repo, pkhex))
            return {"ok": True, "version": "0.23.0", "api": "1.3",
                    "serial_ready": True, "firmware_ready": True,
                    "species": {game: 1 for game in DEFAULT_CONFIG["trainers"]}}
        with patch("startup_checks.find_radio", return_value=None):
            report = check_startup(self.path, self.root, runner=runner)
        self.assertTrue(report.ready)
        self.assertTrue(report.warnings)
        self.assertIn("Console keys", report.text())
        self.assertIn("ESP32 not found", report.text())
        self.assertEqual(calls[0][0], Path(self.cfg["pokeldn_repo"]) / ".venv/bin/python")
        self.assertEqual(calls[1][0], Path(sys.executable))
        self.assertEqual(self.path.read_bytes(), before)

    def test_radio_discovery_uses_same_preference_and_acm_fallback_without_opening_port(self):
        dev = self.root / "dev"
        ids = dev / "serial" / "by-id"
        ids.mkdir(parents=True)
        (ids / "aaa-other-device").touch()
        cp210 = ids / "zzz-Silicon_Labs_CP2102"
        cp210.touch()
        self.assertEqual(find_radio("auto", dev), cp210)
        self.assertEqual(find_radio("esp32:auto", dev), cp210)
        self.assertIsNone(find_radio(str(dev / "missing"), dev))
        cp210.unlink()
        (ids / "aaa-other-device").unlink()
        acm = dev / "ttyACM0"
        acm.touch()
        self.assertEqual(find_radio("auto", dev), acm)

    def test_real_probes_accept_supported_backend_and_reject_old_or_changed_api(self):
        for version, api, ok in (("0.23.0", (1, 3), True), ("0.24.0", (1, 4), True),
                                 ("0.22.2", (1, 3), False), ("0.23.0", (1, 2), False),
                                 ("0.24.0", (2, 3), False)):
            with self.subTest(version=version, api=api):
                repo = self.root / f"backend-{version}-{api[0]}-{api[1]}"
                fake_backend(repo, version=version, api=api)
                result = run_probe(Path(sys.executable), repo, pkhex=True)
                self.assertEqual(result["ok"], ok, result)
                if ok:
                    self.assertEqual(result["species"], {game: 1 for game in DEFAULT_CONFIG["trainers"]})

    def test_broken_pkhex_is_fatal_but_missing_flash_tools_is_only_a_warning(self):
        repo = Path(self.cfg["pokeldn_repo"])
        fake_backend(repo)
        (repo / "esptool.py").unlink()
        # Make the import failure independent of installed packages on CI.
        (repo / "esptool.py").write_text("raise ImportError('esptool unavailable')", encoding="utf-8")
        result = run_probe(Path(sys.executable), repo, pkhex=True)
        self.assertTrue(result["ok"], result)
        self.assertFalse(result["firmware_ready"])
        self.assertIn("esptool unavailable", result["firmware_warning"])
        pokemon = repo / "pokeldn/pokemon.py"
        with pokemon.open("a", encoding="utf-8") as fh:
            fh.write("\ndef broken(game): raise RuntimeError('PKHeX missing')\nSERVICE.species = broken\n")
        result = run_probe(Path(sys.executable), repo, pkhex=True)
        self.assertFalse(result["ok"])
        self.assertIn("PKHeX missing", result["error"])

    def test_bank_capability_is_optional_for_old_backend_and_detected_for_api_14(self):
        repo = Path(self.cfg["pokeldn_repo"])
        fake_backend(repo, version="0.24.0", api=(1, 4))
        missing = run_probe(Path(sys.executable), repo, pkhex=True)
        self.assertTrue(missing["ok"])
        self.assertFalse(missing.get("bank_ready", False))
        app = repo / "pokeldn/app"
        app.mkdir(exist_ok=True)
        (app / "__init__.py").touch()
        (app / "bank.py").write_text(
            "class TradeSession:\n    def advance(self, count): pass\n"
            + "\n".join(f"def {name}(*a, **kw): pass" for name in
                ("entries", "find", "import_file", "deposit", "destinations", "offer", "remove")), encoding="utf-8")
        (app / "received.py").write_text("def trades_done(line): pass\n", encoding="utf-8")
        supported = run_probe(Path(sys.executable), repo, pkhex=True)
        self.assertTrue(supported["ok"])
        self.assertTrue(supported["bank_ready"])

    def test_frontend_does_not_require_full_catalog_dependencies_but_backend_still_checks_api(self):
        repo = Path(self.cfg["pokeldn_repo"])
        fake_backend(repo)
        (repo / "pokeldn/plugins.py").write_text(
            "raise ModuleNotFoundError(\"No module named 'Crypto'\", name='Crypto')\n", encoding="utf-8")
        frontend = run_probe(Path(sys.executable), repo, pkhex=False)
        self.assertTrue(frontend["ok"], frontend)
        backend = run_probe(Path(sys.executable), repo, pkhex=True)
        self.assertFalse(backend["ok"])
        self.assertIn("Crypto", backend["error"])
        # Real builder dependency failures must still block the touchscreen.
        with (repo / "pokeldn/gifts.py").open("a", encoding="utf-8") as fh:
            fh.write("\nraise ModuleNotFoundError('Builder dependency missing')\n")
        frontend = run_probe(Path(sys.executable), repo, pkhex=False)
        self.assertFalse(frontend["ok"])
        self.assertIn("Builder dependency missing", frontend["error"])

    @unittest.skipUnless(os.name == "posix", "Pi process-group cleanup uses POSIX")
    def test_hung_probe_cleans_only_its_own_helper_and_leaves_other_processes_running(self):
        repo = Path(self.cfg["pokeldn_repo"])
        fake_backend(repo)
        helper = repo / "helper.py"
        marker = repo / "helper-stopped"
        helper.write_text("import signal,time,pathlib,sys\n"
            f"def stop(*a): pathlib.Path({str(marker)!r}).touch(); sys.exit(0)\n"
            "signal.signal(signal.SIGTERM, stop)\n"
            "while True: time.sleep(.01)\n", encoding="utf-8")
        with (repo / "pokeldn/pokemon.py").open("a", encoding="utf-8") as fh:
            fh.write(f"\nimport subprocess,sys,time\nchild = subprocess.Popen([sys.executable, {str(helper)!r}])\n"
                     "def hung(game):\n    while True: time.sleep(.01)\nSERVICE.species = hung\n")
        unrelated = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        try:
            result = run_probe(Path(sys.executable), repo, pkhex=True, timeout=1)
            self.assertFalse(result["ok"])
            self.assertIn("timed out", result["error"])
            self.assertTrue(marker.exists())
            self.assertIsNone(unrelated.poll())
        finally:
            unrelated.terminate()
            unrelated.wait(timeout=5)

    @unittest.skipUnless(os.name == "posix" and shutil.which("bash"), "Installer runs on Linux")
    def test_installer_uses_override_config_and_custom_backend_without_overwriting_settings(self):
        repo = Path(self.cfg["pokeldn_repo"])
        fake_backend(repo)
        before = self.path.read_bytes()
        app = self.root / "tradebox"
        app.mkdir()
        source = Path(__file__).resolve().parents[1]
        for name in ("install.sh", "startup_checks.py", "config.example.json", "tradebox.py",
                     "session_control.py", "esp32_manager.py", "start-tradebox.sh",
                     "bank_backend.py", "bank_client.py", "bank_ui.py"):
            shutil.copyfile(source / name, app / name)
        env = dict(os.environ, POKEMON_TRADEBOX_CONFIG=str(self.path), HOME=str(self.root / "unrelated-home"))
        result = subprocess.run(["bash", str(app / "install.sh")], cwd=self.root, env=env,
                                text=True, capture_output=True, timeout=40)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(str(self.path), result.stdout)
        self.assertIn("PokeLDN 0.23.0, API 1.3", result.stdout)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertFalse((app / "config.json").exists())


if __name__ == "__main__":
    unittest.main()
