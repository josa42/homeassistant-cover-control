"""Diagnostics: the full decision trace, which is too big for the recorder."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from . import CoverControlConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: CoverControlConfigEntry
) -> dict[str, Any]:
    """Return hub config plus the last decisions for every cover."""
    coordinator = entry.runtime_data
    return {
        "hub": coordinator.hub_config,
        "master_enabled": coordinator.master_enabled,
        "covers": {
            runtime.cover_entity: {
                "title": runtime.title,
                "config": runtime.config,
                "enabled": runtime.enabled,
                "episode": {
                    "active": runtime.state.active,
                    "intent": runtime.state.intent,
                    "override": runtime.state.override,
                    "storm_latched": runtime.state.storm_latched,
                    "gate_false_since": (
                        runtime.state.gate_false_since.isoformat()
                        if runtime.state.gate_false_since
                        else None
                    ),
                },
                "expected_position": runtime.expected_position,
                "decisions": [d.as_dict() for d in runtime.history],
            }
            for runtime in coordinator.runtimes.values()
        },
    }
