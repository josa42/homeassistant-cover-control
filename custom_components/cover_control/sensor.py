"""Decision sensors: the compact, recorder-safe half of the debug story."""

from __future__ import annotations

from typing import Any, ClassVar

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import CoverControlConfigEntry
from .const import SUBENTRY_TYPE_COVER, Intent
from .coordinator import CoverControlCoordinator, CoverRuntime
from .entity import ControlledCoverEntity, HubEntity


def _count(runtimes, intent: Intent) -> int:
    """How many covers currently hold the given intent."""
    return sum(1 for r in runtimes if r.decision and r.decision.intent is intent)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CoverControlConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the hub status sensor and one decision sensor per cover."""
    coordinator = entry.runtime_data
    async_add_entities([HubStatusSensor(coordinator)])

    for subentry_id, subentry in entry.subentries.items():
        if subentry.subentry_type != SUBENTRY_TYPE_COVER:
            continue
        runtime = coordinator.runtimes.get(subentry_id)
        if runtime is None:
            continue
        async_add_entities(
            [DecisionSensor(coordinator, runtime)], config_subentry_id=subentry_id
        )


class HubStatusSensor(HubEntity, SensorEntity):
    """How many covers are currently being controlled."""

    # The unit is translated, which Home Assistant only allows without a native one.

    def __init__(self, coordinator: CoverControlCoordinator) -> None:
        super().__init__(coordinator, "status")

    @property
    def native_value(self) -> int:
        return sum(1 for r in self.coordinator.runtimes.values() if r.state.active)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        runtimes = self.coordinator.runtimes.values()
        return {
            "total": len(self.coordinator.runtimes),
            "shading": _count(runtimes, Intent.COOLING),
            "heating": _count(runtimes, Intent.HEATING),
            "overridden": sum(1 for r in runtimes if r.state.override),
            "paused": sum(1 for r in runtimes if r.is_paused),
            "storm": sum(1 for r in runtimes if r.state.storm_latched),
            "enabled": self.coordinator.master_enabled,
        }


class DecisionSensor(ControlledCoverEntity, SensorEntity):
    """The current intent, with a compact summary of why."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options: ClassVar[list[str]] = [intent.value for intent in Intent]

    def __init__(
        self, coordinator: CoverControlCoordinator, runtime: CoverRuntime
    ) -> None:
        super().__init__(coordinator, runtime, "decision")

    @property
    def native_value(self) -> str | None:
        runtime = self.runtime
        if runtime is None or runtime.decision is None:
            return None
        return runtime.decision.intent.value

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        runtime = self.runtime
        if runtime is None or runtime.decision is None:
            return {}
        return runtime.decision.as_attributes()

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()
