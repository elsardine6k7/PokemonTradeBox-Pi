#!/bin/bash
set -euo pipefail
APP_DIR="$(cd "$(dirname "$0")" && pwd)"
AUTOSTART=0
if [[ "${1:-}" == "--autostart" ]]; then AUTOSTART=1; fi
mkdir -p "$APP_DIR/logs" "$APP_DIR/gifts"
CONFIG_PATH="$(python3 -c 'import sys; from pathlib import Path; sys.path.insert(0, sys.argv[1]); from startup_checks import config_path; print(config_path(Path(sys.argv[1])))' "$APP_DIR")"
if [[ ! -e "$CONFIG_PATH" ]]; then
  mkdir -p "$(dirname "$CONFIG_PATH")"
  cp "$APP_DIR/config.example.json" "$CONFIG_PATH"
  echo "Created $CONFIG_PATH"
fi
chmod +x "$APP_DIR/tradebox.py" "$APP_DIR/start-tradebox.sh" "$APP_DIR/esp32_manager.py"
python3 -m py_compile "$APP_DIR/tradebox.py" "$APP_DIR/esp32_manager.py" "$APP_DIR/session_control.py" "$APP_DIR/startup_checks.py" "$APP_DIR/bank_backend.py" "$APP_DIR/bank_client.py" "$APP_DIR/bank_ui.py" "$APP_DIR/simulated_gifts.py"
python3 "$APP_DIR/startup_checks.py" --config "$CONFIG_PATH" --frontend-python /usr/bin/python3
if [[ "$AUTOSTART" -eq 1 ]]; then
  mkdir -p "$HOME/.config/labwc"
  AUTOSTART_FILE="$HOME/.config/labwc/autostart"
  LINE="(sleep 5; $APP_DIR/start-tradebox.sh >> $APP_DIR/autostart.log 2>&1) &"
  touch "$AUTOSTART_FILE"
  if ! grep -Fqx "$LINE" "$AUTOSTART_FILE"; then printf '\n%s\n' "$LINE" >> "$AUTOSTART_FILE"; fi
  echo "Labwc autostart enabled."
fi
echo
echo "Install check complete."
echo "Config: $CONFIG_PATH"
echo "Run: $APP_DIR/start-tradebox.sh"
