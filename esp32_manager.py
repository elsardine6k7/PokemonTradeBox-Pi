#!/usr/bin/env python3

import argparse
import json
import os
import sys
import time
from pathlib import Path


def load_board(repo):
    repo = Path(repo).expanduser().resolve()

    if not repo.is_dir():
        raise RuntimeError(f"pokeldn repo not found: {repo}")

    sys.path.insert(0, str(repo))
    os.chdir(repo)

    from gui import board

    return board


def board_status(board, port):
    identity = board.identify(port, blink=False)

    chip = identity.chip

    # Older/unversioned firmware may answer HELLO without identifying
    # the chip. In that case ask the ROM bootloader and reset it back.
    if not chip:
        chip = board.detect_chip(port)

    downloaded_version = ""
    image_path = ""

    if chip:
        try:
            image_path = board.image_for("radio", chip)
            downloaded_version = board.image_version(image_path)
        except Exception:
            pass

    return {
        "ok": True,
        "port": str(port),
        "chip": chip or "Unknown",
        "firmware": identity.firmware,
        "installed_version": identity.firmware_version or "Unknown",
        "protocol": identity.protocol,
        "protocol_current": bool(identity.current),
        "downloaded_version": downloaded_version or "Not downloaded",
        "image_path": image_path,
    }


def do_check(board, port):
    return board_status(board, port)


def do_download(board, port):
    tag = board.download_firmware(
        say=lambda message: print(message, file=sys.stderr, flush=True)
    )

    result = board_status(board, port)
    result["release"] = tag
    return result


def do_flash(board, port):
    # Identify first so we know which image this board requires.
    current = board_status(board, port)
    chip = current["chip"]

    if not chip or chip == "Unknown":
        raise RuntimeError("Could not determine the connected ESP32 chip.")

    image = board.image_for("radio", chip)

    if not Path(image).is_file():
        raise RuntimeError(
            "No downloaded firmware image is available. "
            "Run CHECK / DOWNLOAD LATEST first."
        )

    version = board.image_version(image)

    if not version:
        raise RuntimeError(
            "The downloaded firmware image has no readable version."
        )

    print(
        f"[tradebox] Flashing {chip} with pokeldn radio firmware {version}.",
        file=sys.stderr,
        flush=True,
    )

    # pokeldn performs chip detection, image/chip validation,
    # checksum validation and the esptool flash.
    board.flash(port, kind="radio")

    time.sleep(2)

    result = board_status(board, port)
    result["flashed_version"] = version
    return result


def main():
    parser = argparse.ArgumentParser(
        description="PokemonTradeBox-Pi ESP32 firmware helper"
    )

    parser.add_argument(
        "action",
        choices=("check", "download", "flash"),
    )

    parser.add_argument(
        "--repo",
        required=True,
        help="pokeldn source checkout",
    )

    parser.add_argument(
        "--port",
        required=True,
        help="ESP32 serial port",
    )

    args = parser.parse_args()

    try:
        board = load_board(args.repo)

        if args.action == "check":
            result = do_check(board, args.port)

        elif args.action == "download":
            result = do_download(board, args.port)

        else:
            result = do_flash(board, args.port)

        print(json.dumps(result), flush=True)
        return 0

    except Exception as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            ),
            flush=True,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
