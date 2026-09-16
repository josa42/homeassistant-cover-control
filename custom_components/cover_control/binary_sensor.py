"""Storm and override indicators."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import CoverControlConfigEntry
from .const import SUBENTRY_TYPE_COVER
from .coordinator import CoverControlCoordinator, CoverRuntime
from .entity import ControlledCoverEntity, HubEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CoverControlConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the storm indicator and one override indicator per cover."""
    coordinator = entry.runtime_data
    async_add_entities([StormActiveSensor(coordinator)])

    for subentry_id, subentry in entry.subentries.items():
        if subentry.subentry_type != SUBENTRY_TYPE_COVER:
            continue
        runtime = coordinator.runtimes.get(subentry_id)
        if runtime is None:
            continue
        async_add_entities(
            [OverrideActiveSensor(coordinator, runtime)],
            config_subentry_id=subentry_id,
        )


class StormActiveSensor(HubEntity, BinarySensorEntity):
    """On while the wind is above the threshold."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator: CoverControlCoordinator) -> None:
        super().__init__(coordinator, "storm_active")

    @property
    def is_on(self) -> bool:
        return any(r.state.storm_latched for r in self.coordinator.runtimes.values())


class OverrideActiveSensor(ControlledCoverEntity, BinarySensorEntity):
    """On while a human holds this cover."""

    def __init__(
        self, coordinator: CoverControlCoordinator, runtime: CoverRuntime
    ) -> None:
        super().__init__(coordinator, runtime, "override_active")

    @property
    def is_on(self) -> bool:
        runtime = self.runtime
        return bool(runtime and runtime.state.override)
