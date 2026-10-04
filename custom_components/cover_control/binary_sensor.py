"""Storm, storm pause, override and pause indicators."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util import dt as dt_util

from . import CoverControlConfigEntry
from .const import SUBENTRY_TYPE_COVER
from .coordinator import CoverControlCoordinator, CoverRuntime
from .entity import ControlledCoverEntity, HubEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CoverControlConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the storm indicator plus override and pause indicators per cover."""
    coordinator = entry.runtime_data
    async_add_entities([StormActiveSensor(coordinator), StormPausedSensor(coordinator)])

    for subentry_id, subentry in entry.subentries.items():
        if subentry.subentry_type != SUBENTRY_TYPE_COVER:
            continue
        runtime = coordinator.runtimes.get(subentry_id)
        if runtime is None:
            continue
        async_add_entities(
            [
                OverrideActiveSensor(coordinator, runtime),
                PausedSensor(coordinator, runtime),
            ],
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


class StormPausedSensor(HubEntity, BinarySensorEntity, RestoreEntity):
    """On while storm protection is paused, with the deadline as an attribute.

    Restores the pause across a restart for the same reason a cover's pause
    sensor does.
    """

    def __init__(self, coordinator: CoverControlCoordinator) -> None:
        super().__init__(coordinator, "storm_paused")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is None:
            return
        raw = last.attributes.get("paused_until")
        until = dt_util.parse_datetime(raw) if isinstance(raw, str) else None
        if until is None or until <= dt_util.utcnow():
            return
        await self.coordinator.async_set_storm_paused_until(until)

    @property
    def is_on(self) -> bool:
        return self.coordinator.storm_paused

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        until = self.coordinator.storm_paused_until if self.is_on else None
        return {"paused_until": until.isoformat() if until else None}


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


class PausedSensor(ControlledCoverEntity, BinarySensorEntity, RestoreEntity):
    """On while a pause is running, with the deadline as an attribute.

    This is also where a pause survives a restart. Episode state is rebuilt
    from scratch on every start, so without restoring it here a Home Assistant
    update in the evening would quietly hand the covers back before sunrise.
    """

    def __init__(
        self, coordinator: CoverControlCoordinator, runtime: CoverRuntime
    ) -> None:
        super().__init__(coordinator, runtime, "paused")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is None:
            return
        raw = last.attributes.get("paused_until")
        until = dt_util.parse_datetime(raw) if isinstance(raw, str) else None
        if until is None or until <= dt_util.utcnow():
            return
        await self.coordinator.async_set_paused_until(self._subentry_id, until)

    @property
    def is_on(self) -> bool:
        runtime = self.runtime
        return bool(runtime and runtime.is_paused)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        runtime = self.runtime
        until = runtime.state.paused_until if runtime else None
        return {"paused_until": until.isoformat() if until else None}
