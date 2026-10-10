#!/bin/bash
set -euo pipefail
APP_DIR="$(cd "$(dirname "$0")" && pwd)"
AUTOSTART=0
if [[ "${1:-}" == "--autostart" ]]; then AUTOSTART=1; fi
mkdir -p "$APP_DIR/logs" "$APP_DIR/gifts"
if [[ ! -f "$APP_DIR/config.json" ]]; then
  cp "$APP_DIR/config.example.json" "$APP_DIR/config.json"
  echo "Created $APP_DIR/config.json"
fi
chmod +x "$APP_DIR/tradebox.py" "$APP_DIR/start-tradebox.sh"
python3 -m py_compile "$APP_DIR/tradebox.py"
if [[ ! -d "$HOME/pokeldn" ]]; then echo "WARNING: ~/pokeldn was not found. Install pokeldn first or edit config.json."; fi
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
echo "Next: edit $APP_DIR/config.json with your trainer IDs and paths."
echo "Run: $APP_DIR/start-tradebox.sh"
