#!/usr/bin/env python3
"""Bridge Xbox/XInput rumble feedback to the MX Master 4."""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

try:
    import requests
except Exception:  # pragma: no cover
    requests = None

try:
    import websocket
except Exception:  # pragma: no cover
    websocket = None

from core.service_client import ServiceClient

WAVEFORM_INDEX = {
    "sharp_collision": 0,
    "sharp_state_change": 1,
    "knock": 2,
    "damp_collision": 3,
    "mad": 4,
    "ringing": 5,
    "subtle_collision": 6,
    "completed": 7,
    "jingle": 8,
    "damp_state_change": 9,
    "firework": 10,
    "happy_alert": 11,
    "wave": 12,
    "angry_alert": 13,
    "square": 14,
}

DEFAULT_CONFIG = {
    "backend": "mastermice",
    "hapticweb_base": "https://local.jmw.nz:41443",
    "websocket_url": "wss://local.jmw.nz:41443/ws",
    "use_websocket": True,
    "min_strength": 18,
    "cooldown_ms": 35,
    "repeat_ms": 70,
    "mapping": {
        "light": "subtle_collision",
        "medium": "knock",
        "heavy": "sharp_collision",
        "high_frequency": "sharp_state_change",
        "mixed": "damp_collision",
    },
}

WAVEFORM_PULSE = {
    "sharp_collision": 0x08,
    "sharp_state_change": 0x08,
    "knock": 0x04,
    "damp_collision": 0x04,
    "mad": 0x08,
    "ringing": 0x04,
    "subtle_collision": 0x02,
    "completed": 0x02,
    "jingle": 0x02,
    "damp_state_change": 0x04,
    "firework": 0x08,
    "happy_alert": 0x02,
    "wave": 0x04,
    "angry_alert": 0x08,
    "square": 0x04,
}


@dataclass
class HapticConfig:
    backend: str
    base_url: str
    websocket_url: str
    use_websocket: bool
    min_strength: int
    cooldown_ms: int
    repeat_ms: int
    mapping: dict[str, str]

    @classmethod
    def load(cls, path: str | Path = "config.json") -> "HapticConfig":
        path = Path(path)
        if not path.exists():
            path.write_text(json.dumps(DEFAULT_CONFIG, indent=2), encoding="utf-8")
        data = dict(DEFAULT_CONFIG)
        data.update(json.loads(path.read_text(encoding="utf-8")))
        return cls(
            backend=data.get("backend", "mastermice"),
            base_url=data["hapticweb_base"].rstrip("/"),
            websocket_url=data["websocket_url"],
            use_websocket=bool(data.get("use_websocket", True)),
            min_strength=int(data.get("min_strength", 18)),
            cooldown_ms=int(data.get("cooldown_ms", 35)),
            repeat_ms=int(data.get("repeat_ms", 70)),
            mapping=dict(data["mapping"]),
        )


class HapticWeb:
    """Communicate with the Logitech HapticWeb plugin."""

    def __init__(self, cfg: HapticConfig):
        self.cfg = cfg
        self._ws = None
        self._lock = threading.Lock()

    def healthcheck(self) -> dict:
        if requests is None:
            raise RuntimeError("Missing dependency: requests")
        r = requests.get(f"{self.cfg.base_url}/", timeout=1.5)
        r.raise_for_status()
        return r.json()

    def waveforms(self) -> list[str]:
        if requests is None:
            raise RuntimeError("Missing dependency: requests")
        r = requests.get(f"{self.cfg.base_url}/waveforms", timeout=1.5)
        r.raise_for_status()
        return r.json().get("waveforms", [])

    def connect(self) -> None:
        if not self.cfg.use_websocket:
            return
        if websocket is None:
            raise RuntimeError("Missing dependency: websocket-client")
        self._ws = websocket.create_connection(self.cfg.websocket_url, timeout=1.5)

    def close(self) -> None:
        with self._lock:
            if self._ws is not None:
                try:
                    self._ws.close()
                except Exception:
                    pass
                self._ws = None

    def trigger(self, waveform: str) -> None:
        if waveform not in WAVEFORM_INDEX:
            raise ValueError(f"Unknown waveform: {waveform}")

        with self._lock:
            if self.cfg.use_websocket:
                try:
                    if self._ws is None:
                        self.connect()
                    self._ws.send_binary(bytes([WAVEFORM_INDEX[waveform]]))
                    return
                except Exception:
                    self.close()

            if requests is None:
                raise RuntimeError("Missing dependency: requests")
            r = requests.post(
                f"{self.cfg.base_url}/haptic/{waveform}",
                data=b"",
                timeout=0.35,
            )
            r.raise_for_status()


class MasterMiceOutput:
    """Send mapped rumble pulses through the MasterMice named pipe."""

    def __init__(self):
        self.client = ServiceClient()

    def connect(self) -> None:
        if not self.client.connect():
            raise RuntimeError("MasterMice service is not reachable")

    def close(self) -> None:
        self.client.disconnect()

    def trigger(self, waveform: str) -> None:
        pulse = WAVEFORM_PULSE.get(waveform)
        if pulse is None:
            raise ValueError(f"Unknown waveform: {waveform}")
        if not self.client.connected:
            self.connect()
        if not self.client.haptic_trigger(pulse):
            raise RuntimeError(f"MasterMice rejected haptic pulse 0x{pulse:02X}")


class RumbleMapper:
    """Map Xbox rumble to an MX Master 4 waveform."""

    def __init__(self, cfg: HapticConfig, output):
        self.cfg = cfg
        self.output = output
        self.last_sent_at = 0.0
        self.last_waveform = None

    def _choose(self, large: int, small: int) -> str | None:
        strength = max(large, small)
        if strength < self.cfg.min_strength:
            return None

        total = max(1, large + small)
        high_ratio = small / total

        if small >= 90 and high_ratio >= 0.65:
            return self.cfg.mapping["high_frequency"]
        if large >= 70 and small >= 55:
            return self.cfg.mapping["mixed"]
        if strength >= 185:
            return self.cfg.mapping["heavy"]
        if strength >= 90:
            return self.cfg.mapping["medium"]
        return self.cfg.mapping["light"]

    def on_rumble(self, large: int, small: int) -> tuple[bool, str | None]:
        now = time.perf_counter()
        waveform = self._choose(large, small)

        if waveform is None:
            self.last_waveform = None
            return False, None

        cooldown = self.cfg.cooldown_ms / 1000.0
        repeat = self.cfg.repeat_ms / 1000.0
        changed = waveform != self.last_waveform
        enough_for_change = (now - self.last_sent_at) >= cooldown
        enough_for_repeat = (now - self.last_sent_at) >= repeat

        if (changed and enough_for_change) or enough_for_repeat:
            self.output.trigger(waveform)
            self.last_sent_at = now
            self.last_waveform = waveform
            return True, waveform

        return False, waveform


def _show_missing_dependency(message: str) -> int:
    print(message, file=sys.stderr)
    print("Install dependencies with: python -m pip install vgamepad requests websocket-client", file=sys.stderr)
    return 2


def _load_gamepad_module():
    try:
        import vgamepad as vg
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            "Missing dependency: vgamepad. Install it with: python -m pip install vgamepad requests websocket-client"
        ) from exc
    return vg


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Forward Xbox/XInput rumble to Logitech MX Master 4 haptics via HapticWeb."
    )
    parser.add_argument("--config", default="config.json", help="Path to config.json")
    parser.add_argument("--verbose", action="store_true", help="Print each rumble event")
    parser.add_argument("--test-waveform", help="Trigger a single waveform once")
    parser.add_argument(
        "--backend", choices=("mastermice", "hapticweb"),
        help="Haptic output backend (default: config value or mastermice)",
    )
    args = parser.parse_args()

    config_path = Path(args.config)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    cfg = HapticConfig.load(config_path)
    backend = args.backend or cfg.backend

    if args.test_waveform:
        haptic = MasterMiceOutput() if backend == "mastermice" else HapticWeb(cfg)
        try:
            haptic.trigger(args.test_waveform)
        except Exception as exc:
            print(f"Waveform failed: {exc}", file=sys.stderr)
            haptic.close()
            return 2
        haptic.close()
        print(f"Triggered {args.test_waveform}")
        return 0

    try:
        vg = _load_gamepad_module()
    except RuntimeError as exc:
        return _show_missing_dependency(str(exc))

    haptic = MasterMiceOutput() if backend == "mastermice" else HapticWeb(cfg)
    if backend == "mastermice":
        print("Connecting to MasterMice service...")
        try:
            haptic.connect()
            print("  OK: MasterMice service connected")
        except Exception as exc:
            print(f"\nMasterMice service is not reachable: {exc}")
            return 2
    else:
        print("Checking HapticWebPlugin...")
        try:
            info = haptic.healthcheck()
            waveforms = haptic.waveforms()
            print(f"  OK: {info.get('service', 'HapticWebPlugin')} {info.get('version', '')}")
            print(f"  {len(waveforms)} waveforms available")
        except Exception as exc:
            print("\nHapticWebPlugin is not reachable.")
            print("Install/enable HapticWeb in Logi Options+ and retry.")
            print(f"Technical detail: {exc}")
            return 2

    mapper = RumbleMapper(cfg, haptic)
    print("Creating virtual Xbox 360 controller...")
    gamepad = vg.VX360Gamepad()
    callback_lock = threading.Lock()

    def on_notification(client, target, large_motor, small_motor, led_number, user_data):
        with callback_lock:
            large = int(large_motor)
            small = int(small_motor)
            try:
                sent, waveform = mapper.on_rumble(large, small)
                if args.verbose and (large or small):
                    flag = " -> " + (waveform or "") if sent else ""
                    print(f"rumble large={large:3d} small={small:3d}{flag}")
            except Exception as exc:
                print(f"Haptic output error: {exc}", file=sys.stderr)

    gamepad.register_notification(callback_function=on_notification)
    gamepad.update()

    print()
    print("READY")
    print("A virtual Xbox 360 controller is now present.")
    print("Start the game and make sure it uses this virtual controller for rumble.")
    print("Press Ctrl+C to stop.")
    print()
    print(f"Config file: {config_path}")

    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        try:
            gamepad.unregister_notification()
        except Exception:
            pass
        haptic.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
