"""Configuration resolution and the decision record.

The decision record is the whole point of the "why did it just do that"
requirement: every evaluation produces one immutable object carrying the inputs
it read, the gates it applied, the geometry it computed and the action it took.
Nothing may move a cover without producing one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .const import DEFAULTS, OVERRIDABLE, Intent, Reason


@dataclass(frozen=True, slots=True)
class Setting:
    """A resolved setting plus where it came from."""

    value: Any
    source: str  # "cover" | "hub" | "default"

    def as_dict(self) -> dict[str, Any]:
        return {"value": self.value, "source": self.source}


class EffectiveConfig:
    """Resolves hub defaults against per-cover overrides.

    Keeping the source alongside the value is what lets a decision explain
    *why* a threshold was 22 and not 25 without the reader having to open two
    config dialogs and diff them.
    """

    def __init__(self, hub: dict[str, Any], cover: dict[str, Any]) -> None:
        self._hub = hub
        self._cover = cover

    def resolve(self, key: str) -> Setting:
        """Resolve one overridable key."""
        if key in self._cover and self._cover[key] is not None:
            return Setting(self._cover[key], "cover")
        if key in self._hub and self._hub[key] is not None:
            return Setting(self._hub[key], "hub")
        return Setting(DEFAULTS.get(key), "default")

    def get(self, key: str) -> Any:
        """Resolve a key and return just the value."""
        return self.resolve(key).value

    def cover(self, key: str, default: Any = None) -> Any:
        """Read a cover-only setting (geometry, type, storm action)."""
        value = self._cover.get(key)
        return default if value is None else value

    def snapshot(self) -> dict[str, dict[str, Any]]:
        """Every overridable setting with its value and source, for the record."""
        return {key: self.resolve(key).as_dict() for key in OVERRIDABLE}


@dataclass(frozen=True, slots=True)
class Gate:
    """One condition that was evaluated, and what it concluded."""

    name: str
    passed: bool
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "passed": self.passed, "detail": self.detail}


@dataclass(frozen=True, slots=True)
class Decision:
    """One complete evaluation of one cover."""

    timestamp: datetime
    cover_entity: str
    intent: Intent
    reason: Reason
    message: str
    target_position: int | None = None
    target_tilt: int | None = None
    #: A command was warranted, whether or not one was actually sent. In dry
    #: run this stays true while ``acted`` is false, which is what lets the
    #: dashboard show what would have happened.
    would_move: bool = False
    acted: bool = False
    dry_run: bool = False
    blocked_by: str | None = None
    episode_active: bool = False
    inputs: dict[str, Any] = field(default_factory=dict)
    gates: list[Gate] = field(default_factory=list)
    geometry: dict[str, Any] = field(default_factory=dict)
    settings: dict[str, Any] = field(default_factory=dict)
    #: Why the brightness gate concluded what it did. Empty when an earlier
    #: gate returned before brightness was ever evaluated.
    brightness: dict[str, Any] = field(default_factory=dict)

    def gate_passed(self, name: str) -> bool | None:
        """Whether one gate held, or None if it was never reached."""
        for gate in self.gates:
            if gate.name == name:
                return gate.passed
        return None

    def as_attributes(self) -> dict[str, Any]:
        """Compact form for the sensor.

        Deliberately small and flat: the recorder writes this on every state
        change, so the full trace lives in diagnostics instead.
        """
        return {
            "reason_code": str(self.reason),
            "message": self.message,
            "cover_entity": self.cover_entity,
            "target_position": self.target_position,
            "target_tilt": self.target_tilt,
            "would_move": self.would_move,
            "acted": self.acted,
            "dry_run": self.dry_run,
            "blocked_by": self.blocked_by,
            "episode_active": self.episode_active,
            "sun_on_window": self.geometry.get("sun_on_window"),
            # The conditions that were not readable from anywhere else.
            # Flat booleans rather than the gate list, which the recorder would
            # write out in full on every evaluation.
            "temperature_ok": self.gate_passed("temperature"),
            # Both, because the contact and the gate can disagree: a cover set
            # to keep shading passes the gate with the window wide open, and a
            # reader who only saw the raw contact would call that a bug.
            "window_open": self.inputs.get("window_open"),
            "window_ok": self.gate_passed("window_closed"),
            # The angle the sun actually strikes the window at, which is what
            # decides how far in it reaches: the same elevation far off to the
            # side hardly enters at all. Without it the depth below is a number
            # with nothing behind it.
            "profile_angle": self.geometry.get("profile_angle"),
            "penetration_depth": self.geometry.get("penetration_depth"),
            # Without the limit the depth is a number with nothing to compare
            # it against, and it is the comparison that decides the position.
            "max_penetration_depth": self.geometry.get("max_penetration_depth"),
            "outdoor_temp": self.inputs.get("outdoor_temp"),
            "indoor_temp": self.inputs.get("indoor_temp"),
            "pv_power": self.inputs.get("pv_power"),
            "weather": self.inputs.get("weather"),
            # "Not bright enough" is the reason people ask about most, and
            # the raw weather and PV readings alone do not answer it: what
            # is missing is whether each one passed, and when the PV
            # override takes over. All four are cheap for the recorder.
            "bright": self.brightness.get("bright"),
            "weather_ok": self.brightness.get("weather_ok"),
            "pv_override_active": self.brightness.get("pv_override_active"),
            "pv_override_at": self.brightness.get("pv_override_at"),
            "wind_speed": self.inputs.get("wind_speed"),
        }

    def as_dict(self) -> dict[str, Any]:
        """Full record for diagnostics and the fired event."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "cover_entity": self.cover_entity,
            "intent": str(self.intent),
            "reason_code": str(self.reason),
            "message": self.message,
            "target_position": self.target_position,
            "target_tilt": self.target_tilt,
            "would_move": self.would_move,
            "acted": self.acted,
            "dry_run": self.dry_run,
            "blocked_by": self.blocked_by,
            "episode_active": self.episode_active,
            "inputs": self.inputs,
            "gates": [gate.as_dict() for gate in self.gates],
            "geometry": self.geometry,
            "brightness": self.brightness,
            "settings": self.settings,
        }

    @property
    def notify_signature(self) -> tuple | None:
        """What counts as a change worth notifying about, or None to ignore.

        Only the intent and its reason count. The target drifts by a percent
        on every tick as the sun moves, and in dry run the cover never catches
        up, so a target in the signature meant a notification every tick.

        Transient decisions return None and are skipped entirely: a restart
        makes every cover briefly unavailable, and a debounce is a short hold
        inside an episode that usually recovers. Neither is a change.
        """
        if self.intent is Intent.UNAVAILABLE or self.reason is Reason.DEBOUNCING:
            return None
        return (str(self.intent), str(self.reason), self.dry_run)
