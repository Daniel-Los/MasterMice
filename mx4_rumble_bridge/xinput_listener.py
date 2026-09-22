from __future__ import annotations

import socket
import struct
import threading

from .config import BridgeConfig
from .mapper import RumbleMapper
from .mastermice import MasterMiceClient


class XInputRumbleListener:
    """Receives rumble values from the local XInput proxy DLL."""

    MAGIC = b"MX4RMB1"
    PACKET = struct.Struct("<BHH")

    def __init__(
        self,
        cfg: BridgeConfig,
        client: MasterMiceClient,
        verbose: bool = False,
        port: int = 28765,
    ):
        self.client = client
        self.mapper = RumbleMapper(cfg)
        self.verbose = verbose
        self.port = port
        self._stop = threading.Event()
        self._socket: socket.socket | None = None
        self._thread = threading.Thread(target=self._run, name="xinput-rumble", daemon=True)

    def start(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", self.port))
        sock.settimeout(0.25)
        self._socket = sock
        self._thread.start()
        print(f"Listening for XInput rumble on 127.0.0.1:{self.port}")

    def stop(self) -> None:
        self._stop.set()
        if self._socket is not None:
            self._socket.close()
            self._socket = None
        if self._thread.is_alive():
            self._thread.join(timeout=1.0)

    def _run(self) -> None:
        sock = self._socket
        if sock is None:
            return
        expected = len(self.MAGIC) + self.PACKET.size
        while not self._stop.is_set():
            try:
                packet, _ = sock.recvfrom(64)
            except (socket.timeout, OSError):
                continue
            if len(packet) != expected or not packet.startswith(self.MAGIC):
                continue

            _, left, right = self.PACKET.unpack_from(packet, len(self.MAGIC))
            large = left / 65535.0
            small = right / 65535.0
            event = self.mapper.map(large, small)
            if event is None:
                continue
            if self.verbose:
                print(
                    f"rumble large={large:.2f} small={small:.2f} "
                    f"-> {event.pattern} {event.intensity}%"
                )
            try:
                self.client.send_haptic(event.pattern, event.intensity)
            except Exception as exc:
                print(f"MasterMice haptic error: {exc}")
