from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class BridgeConfig:
    pipe_name: str = r"\\.\pipe\MasterMice"
    min_rumble: float = 0.08
    min_interval_ms: int = 35
    repeat_interval_ms: int = 70
    intensity_change_threshold: int = 10
    patterns: dict[str, str] = field(default_factory=lambda: {
        "weak": "Nudge",
        "medium": "Light",
        "strong": "Strong",
        "very_strong": "Burst",
        "high_frequency": "Tick",
        "mixed": "Buzz",
    })

    @classmethod
    def load(cls, path: str | Path | None = None) -> "BridgeConfig":
        path = Path(path or Path(__file__).with_name("config.json"))
        if not path.exists():
            config = cls()
            path.write_text(json.dumps(config.to_dict(), indent=2), encoding="utf-8")
            return config

        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        config = cls(
            pipe_name=str(data.get("pipe_name", cls.pipe_name)),
            min_rumble=float(data.get("min_rumble", cls.min_rumble)),
            min_interval_ms=int(data.get("min_interval_ms", cls.min_interval_ms)),
            repeat_interval_ms=int(data.get("repeat_interval_ms", cls.repeat_interval_ms)),
            intensity_change_threshold=int(
                data.get("intensity_change_threshold", cls.intensity_change_threshold)
            ),
            patterns={**cls().patterns, **data.get("patterns", {})},
        )
        config.validate()
        return config

    def validate(self) -> None:
        if not 0.0 <= self.min_rumble < 1.0:
            raise ValueError("min_rumble must be between 0.0 and 1.0")
        if self.min_interval_ms <= 0 or self.repeat_interval_ms < self.min_interval_ms:
            raise ValueError("repeat_interval_ms must be >= min_interval_ms > 0")
        if not 0 <= self.intensity_change_threshold <= 100:
            raise ValueError("intensity_change_threshold must be between 0 and 100")
        allowed = {"Nudge", "Light", "Tick", "Strong", "Buzz", "Burst", "Triple", "Double-Buzz"}
        invalid = set(self.patterns.values()) - allowed
        if invalid:
            raise ValueError(f"unsupported haptic patterns: {', '.join(sorted(invalid))}")

    def to_dict(self) -> dict:
        return {
            "pipe_name": self.pipe_name,
            "min_rumble": self.min_rumble,
            "min_interval_ms": self.min_interval_ms,
            "repeat_interval_ms": self.repeat_interval_ms,
            "intensity_change_threshold": self.intensity_change_threshold,
            "patterns": self.patterns,
        }
