from __future__ import annotations

import queue
import threading
import time

import vgamepad as vg

from .config import BridgeConfig
from .mapper import RumbleMapper
from .mastermice import MasterMiceClient


class RumbleController:
    def __init__(self, cfg: BridgeConfig, client: MasterMiceClient, verbose: bool = False):
        self.cfg = cfg
        self.client = client
        self.mapper = RumbleMapper(cfg)
        self.gamepad = vg.VX360Gamepad()
        self.verbose = verbose
        self._events: queue.Queue[tuple[float, float]] = queue.Queue(maxsize=1)
        self._stop = threading.Event()
        self._worker = threading.Thread(target=self._process_events, name="rumble-worker")

    @staticmethod
    def _normalize(value: int | float) -> float:
        value = float(value)
        return max(0.0, min(1.0, value / 255.0 if value > 1.0 else value))

    def start(self) -> None:
        self.gamepad.register_notification(callback_function=self._on_notification)
        self._worker.start()
        self.gamepad.update()

    def stop(self) -> None:
        self._stop.set()
        try:
            self.gamepad.unregister_notification()
        except Exception:
            pass
        if self._worker.is_alive():
            self._worker.join(timeout=2.0)

    def _on_notification(self, client, target, large_motor, small_motor, led_number, user_data):
        large = self._normalize(large_motor)
        small = self._normalize(small_motor)
        try:
            self._events.put_nowait((large, small))
        except queue.Full:
            try:
                self._events.get_nowait()
            except queue.Empty:
                pass
            try:
                self._events.put_nowait((large, small))
            except queue.Full:
                pass

    def _process_events(self) -> None:
        next_retry = 0.0
        while not self._stop.is_set():
            now = time.perf_counter()
            if not self.client.connected and now >= next_retry:
                self.client.connect()
                next_retry = now + 1.0
            try:
                large, small = self._events.get(timeout=0.05)
            except queue.Empty:
                continue
            event = self.mapper.map(large, small)
            if event is None:
                continue
            if self.verbose:
                print(f"rumble large={large:.2f} small={small:.2f} -> {event.pattern} {event.intensity}%")
            try:
                self.client.send_haptic(event.pattern, event.intensity)
            except Exception as exc:
                print(f"MasterMice haptic error: {exc}")
