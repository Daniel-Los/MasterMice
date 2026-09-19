from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import json
import threading
import time
from typing import Any


GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
OPEN_EXISTING = 3
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

kernel32.CreateFileW.restype = wt.HANDLE
kernel32.CreateFileW.argtypes = [
    wt.LPCWSTR, wt.DWORD, wt.DWORD, ctypes.c_void_p,
    wt.DWORD, wt.DWORD, wt.HANDLE,
]
kernel32.ReadFile.restype = wt.BOOL
kernel32.ReadFile.argtypes = [
    wt.HANDLE, ctypes.c_char_p, wt.DWORD,
    ctypes.POINTER(wt.DWORD), ctypes.c_void_p,
]
kernel32.WriteFile.restype = wt.BOOL
kernel32.WriteFile.argtypes = [
    wt.HANDLE, ctypes.c_char_p, wt.DWORD,
    ctypes.POINTER(wt.DWORD), ctypes.c_void_p,
]
kernel32.CloseHandle.restype = wt.BOOL
kernel32.CloseHandle.argtypes = [wt.HANDLE]


class MasterMiceClient:
    """Windows named-pipe client for the MasterMice JSON-lines protocol."""

    def __init__(self, pipe_name: str = r"\\.\pipe\MasterMice"):
        self.pipe_name = pipe_name
        self._handle = None
        self._lock = threading.Lock()
        self._next_id = 1

    @property
    def connected(self) -> bool:
        return self._handle is not None

    def connect(self) -> bool:
        if self._handle is not None:
            return True

        print("MasterMice reconnecting")

        h = kernel32.CreateFileW(
            self.pipe_name,
            GENERIC_READ | GENERIC_WRITE,
            0,
            None,
            OPEN_EXISTING,
            0,
            None,
        )
        if h == INVALID_HANDLE_VALUE or h is None or h == 0:
            self._handle = None
            return False

        self._handle = h
        print("MasterMice connected")
        return True

    def close(self) -> None:
        if self._handle is not None:
            try:
                kernel32.CloseHandle(self._handle)
            except Exception:
                pass
            self._handle = None
            print("MasterMice disconnected")

    def health(self) -> dict[str, Any] | None:
        return self.request("health")

    def send_haptic(self, pattern: str, intensity: int) -> None:
        from .mapper import RumbleMapper

        pulse_type = RumbleMapper.pulse_type_for_name(pattern)
        intensity = max(0, min(100, int(intensity)))
        if self.request("set_haptic", enabled=True, intensity=intensity) is None:
            return
        self.request("haptic_trigger", pulse_type=pulse_type)

    def haptic_trigger(self, pulse_type: int) -> bool:
        return self.request("haptic_trigger", pulse_type=pulse_type) is not None

    def request(self, cmd: str, **params) -> dict[str, Any] | None:
        if self._handle is None:
            if not self.connect():
                return None

        req = {"id": self._next_id, "cmd": cmd}
        self._next_id += 1
        if params:
            req["params"] = params

        raw = (json.dumps(req, separators=(",", ":")) + "\n").encode("utf-8")

        with self._lock:
            written = wt.DWORD(0)
            ok = kernel32.WriteFile(self._handle, raw, len(raw), ctypes.byref(written), None)
            if not ok:
                self.close()
                return None

            try:
                response = self._read_line()
            except OSError:
                self.close()
                return None

        try:
            data = json.loads(response.decode("utf-8"))
        except Exception:
            return None

        if not data.get("ok"):
            return None
        return data

    def _read_line(self) -> bytes:
        if self._handle is None:
            raise OSError("pipe is not open")

        buffer = bytearray()
        one = ctypes.create_string_buffer(1)
        read_n = wt.DWORD(0)

        while True:
            ok = kernel32.ReadFile(self._handle, one, 1, ctypes.byref(read_n), None)
            if not ok or read_n.value == 0:
                if buffer:
                    return bytes(buffer)
                raise OSError("pipe read failed")

            buffer.extend(one.raw[:1])
            if one.raw[:1] == b"\n":
                return bytes(buffer)
