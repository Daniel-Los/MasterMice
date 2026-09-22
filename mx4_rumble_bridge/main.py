from __future__ import annotations

import argparse
from pathlib import Path
import sys
import time

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from mx4_rumble_bridge.config import BridgeConfig
    from mx4_rumble_bridge.mapper import RumbleMapper
else:
    from .config import BridgeConfig
    from .mapper import RumbleMapper


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Forward Xbox/XInput rumble to the Logitech MX Master 4 haptic motor via MasterMice."
    )
    parser.add_argument("--config", type=str, default="config.json", help="Path to config.json")
    parser.add_argument("--test-haptics", action="store_true", help="Test every MasterMice haptic pattern")
    parser.add_argument("--verbose", action="store_true", help="Print sent rumble events")
    parser.add_argument(
        "--xinput-proxy",
        action="store_true",
        help="Receive game rumble from the local xinput1_4.dll proxy instead of a virtual controller",
    )
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    try:
        cfg = BridgeConfig.load(args.config)
    except (OSError, ValueError, TypeError) as exc:
        print(f"Invalid configuration: {exc}", file=sys.stderr)
        return 2

    try:
        if __package__ in (None, ""):
            from mx4_rumble_bridge.mastermice import MasterMiceClient
        else:
            from .mastermice import MasterMiceClient
    except (AttributeError, OSError) as exc:
        print("The MasterMice pipe client requires Windows.", file=sys.stderr)
        print(f"Details: {exc}", file=sys.stderr)
        return 2
    client = MasterMiceClient(cfg.pipe_name)

    if args.xinput_proxy:
        try:
            from .xinput_listener import XInputRumbleListener
        except ImportError:
            from mx4_rumble_bridge.xinput_listener import XInputRumbleListener

        listener = XInputRumbleListener(cfg, client, verbose=args.verbose)
        try:
            listener.start()
            while True:
                time.sleep(1.0)
        except KeyboardInterrupt:
            pass
        finally:
            listener.stop()
            client.close()
        return 0

    if args.test_haptics:
        if not client.connect():
            print(f"Could not connect to {cfg.pipe_name}; is MasterMice running?", file=sys.stderr)
            return 2
        try:
            for pattern in ("Nudge", "Light", "Tick", "Strong", "Buzz", "Burst", "Triple", "Double-Buzz"):
                print(f"Testing {pattern} at 50%")
                client.send_haptic(pattern, 50)
                time.sleep(0.35)
        finally:
            client.close()
        return 0

    try:
        from .controller import RumbleController
    except ImportError:
        try:
            from mx4_rumble_bridge.controller import RumbleController
        except ImportError as exc:
            print("The virtual controller dependency is missing. Install it with: py -m pip install vgamepad", file=sys.stderr)
            print(f"Details: {exc}", file=sys.stderr)
            return 2

    if not client.connect():
        print(f"MasterMice unavailable; retrying when rumble arrives.")

    controller = RumbleController(cfg, client, verbose=args.verbose)
    print(f"Pipe: {cfg.pipe_name}")
    print("Virtual Xbox 360 controller ready. Press Ctrl+C to stop.")
    controller.start()

    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        pass
    finally:
        controller.stop()
        client.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
