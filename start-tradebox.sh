#!/bin/bash
set -e
cd "$(dirname "$0")"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
export WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-0}"
export DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=${XDG_RUNTIME_DIR}/bus}"
export GDK_BACKEND="${GDK_BACKEND:-wayland}"
exec /usr/bin/python3 "$(pwd)/tradebox.py"
