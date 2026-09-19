from __future__ import annotations

import time
from dataclasses import dataclass

from .config import BridgeConfig


@dataclass(frozen=True)
class HapticEvent:
    pattern: str
    intensity: int
    large: float
    small: float


class RumbleMapper:
    PULSE_TYPES = {
        "nudge": 0x01, "light": 0x02, "tick": 0x04, "strong": 0x08,
        "buzz": 0x06, "burst": 0x0A, "triple": 0x0C, "double-buzz": 0x0E,
    }

    def __init__(self, config: BridgeConfig, clock=time.perf_counter):
        self.config = config
        self.clock = clock
        self.last_event: HapticEvent | None = None
        self.last_sent_at = float("-inf")

    def map(self, large: float, small: float) -> HapticEvent | None:
        large = max(0.0, min(1.0, float(large)))
        small = max(0.0, min(1.0, float(small)))
        strength = max(large, small)
        if strength < self.config.min_rumble:
            self.last_event = None
            self.last_sent_at = float("-inf")
            return None

        intensity = max(10, min(100, round(strength * 100)))
        pattern = self._pattern(large, small)
        event = HapticEvent(pattern, intensity, large, small)
        now = self.clock()
        changed = self.last_event is None or pattern != self.last_event.pattern
        intensity_changed = (
            self.last_event is None
            or abs(intensity - self.last_event.intensity) >= self.config.intensity_change_threshold
        )
        elapsed = now - self.last_sent_at
        eligible_change = (
            (changed or intensity_changed)
            and elapsed >= self.config.min_interval_ms / 1000
        )
        if not eligible_change and elapsed < self.config.repeat_interval_ms / 1000:
            return None
        self.last_event = event
        self.last_sent_at = now
        return event

    def _pattern(self, large: float, small: float) -> str:
        patterns = self.config.patterns
        if large >= self.config.min_rumble and small >= self.config.min_rumble:
            combined = large + small
            if combined >= 1.8:
                return patterns["very_strong"]
            return patterns["mixed"]
        if small > large * 1.35:
            if small < 0.5:
                return patterns["high_frequency"]
            if small < 0.8:
                return patterns["medium"]
            return patterns["strong"]
        if large < 0.25:
            return patterns["weak"]
        if large < 0.5:
            return patterns["medium"]
        if large < 0.75:
            return patterns["strong"]
        return patterns["very_strong"]

    @classmethod
    def pulse_type_for_name(cls, pattern: str) -> int:
        key = pattern.lower()
        if key not in cls.PULSE_TYPES:
            raise ValueError(f"unsupported haptic pattern: {pattern}")
        return cls.PULSE_TYPES[key]
